"""Validated model boundaries. Provider selection is explicit; requests never auto-retry."""

import json
import logging
import math
import socket
import ssl
from dataclasses import dataclass, field
from threading import Event
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.observability import start_span

logger = logging.getLogger(__name__)


class ModelProblem(RuntimeError):
    def __init__(
        self, code: str, message: str, *, retryable: bool = False, transport_code: str | None = None
    ):
        super().__init__(message)
        self.code, self.retryable, self.transport_code = code, retryable, transport_code


@dataclass
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str
    usage: dict = field(default_factory=dict)


@dataclass
class RankedItem:
    index: int
    score: float


@dataclass
class Ranking:
    items: list[RankedItem]
    model: str
    usage: dict = field(default_factory=dict)


@dataclass
class ChatReply:
    content: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)


def invalid_response():
    return ModelProblem("invalid_model_response", "模型响应格式或数据校验失败")


def base_url(value: str) -> str:
    try:
        url = urlsplit(value)
        valid = (
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
        )
        _ = url.port
    except ValueError:
        valid = False
    if not valid:
        raise ModelProblem("model_not_configured", "请检查模型服务的 HTTPS Base URL")
    return value.rstrip("/")


def usage_of(body):
    usage = body.get("usage", {})
    if not isinstance(usage, dict):
        return {}
    return {
        k: v
        for k, v in usage.items()
        if k
        in {
            "input_tokens",
            "output_tokens",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
        }
        and type(v) is int
        and v >= 0
    }


def check_status(response):
    status = response.status_code
    if status in {401, 403}:
        raise ModelProblem("model_auth", "模型服务认证失败，请检查对应提供方的 Key 和权限")
    if status == 429:
        raise ModelProblem(
            "model_rate_limited", "模型服务限流或额度不足，请稍后重试", retryable=True
        )
    if status >= 500:
        raise ModelProblem("model_unavailable", "模型服务暂不可用，请稍后重试", retryable=True)
    if not 200 <= status < 300:
        raise ModelProblem("model_request_rejected", "模型服务拒绝请求，请检查模型名、接口与参数")


def json_body(response):
    check_status(response)
    try:
        body = response.json()
    except ValueError:
        raise invalid_response() from None
    if not isinstance(body, dict):
        raise invalid_response()
    if body.get("error") or body.get("code") not in (None, 0, "0"):
        raise ModelProblem("model_request_rejected", "模型服务返回错误，请核对模型配置与可用额度")
    return body


def transport_failure(error):
    cause = error
    for _ in range(8):
        if isinstance(cause, ssl.SSLError):
            return "tls_error", "模型 TLS 连接失败，请检查网络或证书配置"
        if isinstance(cause, socket.gaierror):
            return "dns_error", "模型域名解析失败，请检查网络连接"
        cause = cause.__cause__
        if cause is None:
            break
    for kind, code, message in (
        (httpx.ProxyError, "proxy_error", "模型代理连接失败，请检查代理配置"),
        (httpx.ConnectTimeout, "connect_timeout", "模型连接超时，可点击重试"),
        (httpx.ReadTimeout, "read_timeout", "等待模型响应超时，可点击重试"),
        (httpx.WriteTimeout, "write_timeout", "发送模型请求超时，可点击重试"),
        (httpx.PoolTimeout, "pool_timeout", "模型连接繁忙，请稍后重试"),
        (httpx.ConnectError, "connect_error", "模型连接失败，请检查网络后重试"),
        (httpx.ProtocolError, "protocol_error", "模型连接提前中断，可点击重试"),
    ):
        if isinstance(error, kind):
            return code, message
    return "transport_error", "模型连接中断，可点击重试"


class ModelClient:
    def __init__(self, settings: Settings, *, http=None):
        self.settings = settings
        self._injected = http is not None
        self.http = http if http is not None else self._new_http(settings.model_trust_env)
        self._clients = {settings.model_trust_env: self.http}
        self._stream_cancelled = Event()
        self._stream_response = None

    def _new_http(self, trust_env):
        return httpx.Client(
            timeout=httpx.Timeout(self.settings.model_timeout_seconds, connect=10),
            follow_redirects=False,
            trust_env=trust_env,
        )

    def _trust_env(self, provider):
        if provider == "monkey" and self.settings.monkey_model_trust_env is not None:
            return self.settings.monkey_model_trust_env
        return self.settings.model_trust_env

    def _http(self, provider):
        if self._injected:
            return self.http
        trust_env = self._trust_env(provider)
        if trust_env not in self._clients:
            self._clients[trust_env] = self._new_http(trust_env)
        return self._clients[trust_env]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for client in self._clients.values():
            client.close()

    def _headers(self, provider):
        key = self.settings.qwen_api_key if provider == "qwen" else self.settings.monkey_api_key
        if not key.get_secret_value():
            raise ModelProblem("model_not_configured", "所选模型提供方尚未配置 API Key")
        return {"Authorization": "Bearer " + key.get_secret_value()}

    def _record(self, provider, operation, model, started, status, failure):
        logger.log(
            logging.WARNING if failure else logging.INFO,
            "model_call provider=%s operation=%s model=%s network=%s "
            "elapsed_ms=%d http_status=%s failure=%s",
            provider,
            operation,
            model,
            "environment" if self._trust_env(provider) else "direct",
            round((monotonic() - started) * 1000),
            status,
            failure or "none",
        )

    def _post(self, url, provider, body, *, operation):
        started, status, failure = monotonic(), None, None
        observation = start_span(operation, "llm", provider=provider, model=body["model"])
        observation.__enter__()
        observation.record(
            inputs={"messages": body["messages"]}
            if "messages" in body
            else {"input": body.get("input"), "parameters": body.get("parameters")}
        )
        try:
            response = self._http(provider).post(url, headers=self._headers(provider), json=body)
            status = response.status_code
            result = json_body(response)
            observation.metadata.update(usage_of(result))
            if "choices" in result:
                observation.record(outputs={"choices": result["choices"]})
            elif operation == "rerank":
                observation.record(outputs={"results": result.get("output", {})})
            else:
                observation.record(outputs={"usage": usage_of(result)})
            return result
        except httpx.HTTPError as error:
            failure, message = transport_failure(error)
            raise ModelProblem(
                "model_unavailable", message, retryable=True, transport_code=failure
            ) from None
        except ModelProblem as error:
            failure = error.code
            raise
        finally:
            self._record(provider, operation, body["model"], started, status, failure)
            observation.metadata.update(
                status="failed" if failure else "completed", http_status=status
            )
            if failure:
                observation.metadata["error_code"] = failure
            observation.__exit__(None, None, None)

    def _native_url(self, path):
        root = urlsplit(base_url(self.settings.qwen_base_url))
        return f"{root.scheme}://{root.netloc}/api/v1/" + path

    def embed_texts(
        self, texts: list[str], *, text_type: Literal["query", "document"] = "document"
    ) -> EmbeddingBatch:
        if (
            not texts
            or len(texts) > 20
            or any(not isinstance(t, str) or not t.strip() for t in texts)
        ):
            raise ModelProblem("invalid_model_input", "向量请求需包含 1～20 条非空文本")
        if text_type not in {"query", "document"}:
            raise ModelProblem("invalid_model_input", "向量文本类型必须为 query 或 document")
        if self.settings.embedding_model == "not-configured":
            raise ModelProblem("model_not_configured", "尚未配置向量模型")
        body = self._post(
            self._native_url("services/embeddings/text-embedding/text-embedding"),
            "qwen",
            {
                "model": self.settings.embedding_model,
                "input": {"texts": texts},
                "parameters": {
                    "dimension": self.settings.embedding_dimension,
                    "text_type": text_type,
                },
            },
            operation="embedding",
        )
        output = body.get("output", body)
        entries = output.get("embeddings") if isinstance(output, dict) else None
        if not isinstance(entries, list) or len(entries) != len(texts):
            raise invalid_response()
        ordered = {}
        for item in entries:
            if not isinstance(item, dict):
                raise invalid_response()
            if "index" in item and "text_index" in item and item["index"] != item["text_index"]:
                raise invalid_response()
            index, vector = item.get("index", item.get("text_index")), item.get("embedding")
            if type(index) is not int or index in ordered or not 0 <= index < len(texts):
                raise invalid_response()
            if not isinstance(vector, list) or len(vector) != self.settings.embedding_dimension:
                raise invalid_response()
            if any(
                type(v) not in {int, float} or abs(v) > 3.4e38 or not math.isfinite(v)
                for v in vector
            ):
                raise invalid_response()
            if not any(v != 0 for v in vector):
                raise invalid_response()
            ordered[index] = [float(v) for v in vector]
        return EmbeddingBatch(
            [ordered[i] for i in range(len(texts))], self.settings.embedding_model, usage_of(body)
        )

    def rerank(self, query: str, documents: list[str], *, top_n: int = 8) -> Ranking:
        if (
            not isinstance(query, str)
            or not query.strip()
            or not documents
            or len(documents) > 500
            or any(not isinstance(t, str) or not t.strip() for t in documents)
        ):
            raise ModelProblem("invalid_model_input", "重排需要非空问题及 1～500 条非空候选内容")
        if type(top_n) is not int or top_n < 1:
            raise ModelProblem("invalid_model_input", "重排数量必须为正整数")
        top_n = min(top_n, len(documents))
        body = self._post(
            self._native_url("services/rerank/text-rerank/text-rerank"),
            "qwen",
            {
                "model": self.settings.qwen_rerank_model,
                "input": {"query": query, "documents": documents},
                "parameters": {"top_n": top_n, "return_documents": False},
            },
            operation="rerank",
        )
        output = body.get("output", body)
        entries = output.get("results") if isinstance(output, dict) else None
        if not isinstance(entries, list) or len(entries) != top_n:
            raise invalid_response()
        items, seen = [], set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise invalid_response()
            index, score = entry.get("index"), entry.get("relevance_score")
            if type(index) is not int or index in seen or not 0 <= index < len(documents):
                raise invalid_response()
            if type(score) not in {int, float} or not math.isfinite(score) or not 0 <= score <= 1:
                raise invalid_response()
            seen.add(index)
            items.append(RankedItem(index, float(score)))
        return Ranking(
            sorted(items, key=lambda item: -item.score),
            self.settings.qwen_rerank_model,
            usage_of(body),
        )

    def _chat_request(self, messages, provider, max_tokens, stream):
        provider = provider or self.settings.llm_provider
        if provider not in {"qwen", "monkey"}:
            raise ModelProblem("model_not_configured", "不支持的回答模型提供方")
        if (
            not isinstance(messages, list)
            or not messages
            or any(
                not isinstance(m, dict)
                or m.get("role") not in {"system", "user", "assistant"}
                or not isinstance(m.get("content"), str)
                or not m["content"].strip()
                for m in messages
            )
        ):
            raise ModelProblem("invalid_model_input", "聊天消息需包含非空文本和有效角色")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 32768:
            raise ModelProblem("invalid_model_input", "回答 Token 上限无效")
        model = (
            self.settings.qwen_llm_model if provider == "qwen" else self.settings.monkey_llm_model
        )
        base = base_url(
            self.settings.qwen_base_url if provider == "qwen" else self.settings.monkey_base_url
        )
        if not model:
            raise ModelProblem("model_not_configured", "所选提供方尚未配置回答模型")
        if not urlsplit(base).path:
            base += "/v1"
        # Rebuild messages so callers cannot accidentally forward provider-specific fields.
        body = {
            "model": model,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "stream": stream,
        }
        if provider == "qwen":
            body.update(max_tokens=max_tokens, enable_thinking=False)
        else:
            body.update(max_completion_tokens=max_tokens)
        return provider, model, base + "/chat/completions", body

    def complete(
        self,
        messages: list[dict],
        *,
        provider=None,
        max_tokens=2048,
        purpose="chat",
        json_mode=False,
    ) -> ChatReply:
        provider, model, url, payload = self._chat_request(messages, provider, max_tokens, False)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = self._post(url, provider, payload, operation=purpose)
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise invalid_response()
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise ModelProblem("model_output_truncated", "回答达到输出上限，未完整生成")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if (
            not isinstance(content, str)
            or not content.strip()
            or choice.get("finish_reason") != "stop"
        ):
            raise invalid_response()
        return ChatReply(content, provider, model, usage_of(body))

    def cancel_stream(self):
        self._stream_cancelled.set()
        response = self._stream_response
        if response is not None:
            # Closing an SSL socket from another thread can leave its read blocked
            # until the provider timeout. Shut down this response's connection first.
            network = response.extensions.get("network_stream")
            if network is not None:
                try:
                    connection = network.get_extra_info("socket")
                    if connection is not None:
                        connection.shutdown(socket.SHUT_RDWR)
                except (OSError, ValueError):
                    pass
            try:
                response.close()
            except (httpx.HTTPError, httpx.StreamError):
                pass

    def stream(
        self,
        messages: list[dict],
        *,
        provider=None,
        max_tokens=2048,
        json_mode=False,
        purpose="chat_stream",
    ):
        if self._stream_cancelled.is_set():
            return
        provider, model, url, payload = self._chat_request(messages, provider, max_tokens, True)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started, status, failure = monotonic(), None, "model_stream_incomplete"
        if provider == "qwen":
            payload["stream_options"] = {"include_usage": True}
        observation = start_span(purpose, "llm", provider=provider, model=model)
        observation.__enter__()
        observation.record(inputs={"messages": payload["messages"]})
        generated = [] if observation.recording else None
        finished, has_text = False, False
        try:
            with self._http(provider).stream(
                "POST", url, headers=self._headers(provider), json=payload
            ) as response:
                self._stream_response = response
                if self._stream_cancelled.is_set():
                    failure = "stream_cancelled"
                    return
                status = response.status_code
                check_status(response)
                data = []
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        value = "\n".join(data)
                        data = []
                        if value == "[DONE]":
                            if finished and has_text:
                                failure = None
                                return
                            raise invalid_response()
                        try:
                            event = json.loads(value)
                        except ValueError:
                            raise invalid_response() from None
                        if not isinstance(event, dict) or event.get("error"):
                            raise invalid_response()
                        observation.metadata.update(usage_of(event))
                        choices = event.get("choices", [])
                        if not choices:
                            continue
                        if not isinstance(choices, list) or not isinstance(choices[0], dict):
                            raise invalid_response()
                        choice = choices[0]
                        if choice.get("finish_reason") == "length":
                            raise ModelProblem(
                                "model_output_truncated", "回答达到输出上限，未完整生成"
                            )
                        finished = finished or choice.get("finish_reason") == "stop"
                        delta = choice.get("delta", {})
                        if not isinstance(delta, dict):
                            raise invalid_response()
                        content = delta.get("content")
                        if content is not None and not isinstance(content, str):
                            raise invalid_response()
                        if content:
                            has_text = True
                            if generated is not None:
                                generated.append(content)
                            yield content
                            if self._stream_cancelled.is_set():
                                failure = "stream_cancelled"
                                return
                if self._stream_cancelled.is_set():
                    failure = "stream_cancelled"
                    return
        except (httpx.HTTPError, httpx.StreamError) as error:
            if self._stream_cancelled.is_set():
                failure = "stream_cancelled"
                return
            failure, message = transport_failure(error)
            raise ModelProblem("model_unavailable", message, retryable=True) from None
        except ModelProblem as error:
            failure = error.code
            raise
        except GeneratorExit:
            failure = "stream_closed"
            raise
        finally:
            self._stream_response = None
            self._record(provider, purpose, model, started, status, failure)
            observation.metadata.update(
                status="stopped"
                if failure in {"stream_cancelled", "stream_closed"}
                else "failed"
                if failure
                else "completed",
                http_status=status,
            )
            if failure:
                observation.metadata["error_code"] = failure
            if generated is not None:
                observation.record(
                    outputs={
                        "choices": [
                            {"message": {"role": "assistant", "content": "".join(generated)}}
                        ]
                    }
                )
            observation.__exit__(None, None, None)
        raise ModelProblem(
            "model_stream_incomplete", "回答流提前结束，未收到完整结束标记", retryable=True
        )

"""One explicit, bounded Tavily search. Web material is never enterprise evidence."""

import ipaddress
import json
import math
import re
from datetime import UTC, datetime
from threading import Event
from urllib.parse import urlsplit

import httpx

from app.model_clients import ModelProblem

WEB_REFUSAL = "本次联网查询未找到足够的公开依据，请换一个更具体的问题，或稍后重试。"


class WebSearchProblem(ModelProblem):
    pass


def public_url(value):
    if not isinstance(value, str) or len(value) > 2000 or any(c.isspace() for c in value):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme not in {"http", "https"} or not host or url.username or url.password:
            return False
        if host in {"localhost", "localhost.localdomain"} or host.endswith(
            (".local", ".localhost")
        ):
            return False
        _ = url.port
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return "." in host
    except ValueError:
        return False


class TavilySearch:
    def __init__(self, settings, *, http=None):
        self.settings = settings
        self.http = http
        self.cancelled = Event()
        self.response = None

    def cancel(self):
        self.cancelled.set()
        # Reuse the same cancellation boundary that wakes blocked TLS reads.
        response = self.response
        if response is not None:
            import socket

            network = response.extensions.get("network_stream")
            if network:
                try:
                    connection = network.get_extra_info("socket")
                    if connection is not None:
                        connection.shutdown(socket.SHUT_RDWR)
                except (OSError, ValueError):
                    pass
            try:
                response.close()
            except httpx.HTTPError:
                pass

    def search(self, query):
        if not isinstance(query, str) or not query.strip() or len(query) > 300:
            raise WebSearchProblem("web_query_invalid", "联网检索问题无效，请缩短后重试")
        key = self.settings.tavily_api_key.get_secret_value()
        if not key:
            raise WebSearchProblem("web_search_not_configured", "请先配置 Tavily API Key")
        http = self.http or httpx.Client(
            timeout=httpx.Timeout(self.settings.tavily_timeout_seconds, connect=5),
            trust_env=self.settings.tavily_trust_env,
            follow_redirects=False,
        )
        try:
            if self.cancelled.is_set():
                raise WebSearchProblem("request_stopped", "联网查询已停止")
            with http.stream(
                "POST",
                "https://api.tavily.com/search",
                headers={"Authorization": "Bearer " + key},
                json={
                    "query": query.strip(),
                    "max_results": 5,
                    "search_depth": "basic",
                    "include_answer": False,
                    "include_raw_content": False,
                    "include_images": False,
                },
            ) as response:
                self.response = response
                if response.status_code in {401, 403}:
                    raise WebSearchProblem(
                        "web_search_auth", "联网搜索认证失败，请检查 Tavily 配置"
                    )
                if response.status_code == 429:
                    raise WebSearchProblem(
                        "web_search_rate_limited",
                        "联网搜索限流或额度不足，请稍后重试",
                        retryable=True,
                    )
                if response.status_code != 200:
                    raise WebSearchProblem(
                        "web_search_unavailable", "联网搜索服务暂不可用，请稍后重试", retryable=True
                    )
                raw = bytearray()
                for block in response.iter_bytes():
                    if self.cancelled.is_set():
                        raise WebSearchProblem("request_stopped", "联网查询已停止")
                    raw.extend(block)
                    if len(raw) > 512_000:
                        raise ValueError("oversized search result")
                body = json.loads(raw)
            entries = body.get("results") if isinstance(body, dict) else None
            if not isinstance(entries, list):
                raise ValueError("invalid results")
            results, seen = [], set()
            for entry in entries[:20]:
                if not isinstance(entry, dict):
                    continue
                url, content, title = entry.get("url"), entry.get("content"), entry.get("title")
                if (
                    not public_url(url)
                    or url in seen
                    or not isinstance(content, str)
                    or not content.strip()
                    or not isinstance(title, str)
                ):
                    continue
                seen.add(url)
                score = entry.get("score")
                results.append(
                    {
                        "number": len(results) + 1,
                        "url": url,
                        "title": title[:300],
                        "content": content[:1600],
                        "score": score
                        if type(score) in {float, int} and math.isfinite(score)
                        else None,
                    }
                )
                if len(results) == 5:
                    break
            return {
                "provider": "tavily",
                "query": query.strip(),
                "queried_at": datetime.now(UTC).isoformat(),
                "results": results,
            }
        except httpx.TimeoutException:
            raise WebSearchProblem(
                "web_search_timeout", "联网搜索超时，请稍后重试", retryable=True
            ) from None
        except httpx.HTTPError:
            raise WebSearchProblem(
                "web_search_unavailable", "联网搜索连接失败，请检查网络后重试", retryable=True
            ) from None
        except (ValueError, TypeError):
            raise WebSearchProblem(
                "web_search_invalid_response", "联网搜索返回了无效数据，请稍后重试", retryable=True
            ) from None
        finally:
            self.response = None
            if self.http is None:
                http.close()


def validate_web_answer(raw, sources):
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or type(body.get("answerable")) is not bool:
            raise ValueError()
        if not body["answerable"]:
            return WEB_REFUSAL, [], "refused"
        answer, citations = body["answer"], body["citations"]
        if (
            not isinstance(answer, str)
            or not answer.strip()
            or len(answer) > 16000
            or not isinstance(citations, list)
        ):
            raise ValueError()
        if re.search(r"https?://|\]\s*\(", answer, re.IGNORECASE):
            raise ValueError()
        numbers = [item["source"] for item in citations]
        if (
            not numbers
            or any(type(n) is not int or not 1 <= n <= len(sources) for n in numbers)
            or len(set(numbers)) != len(numbers)
        ):
            raise ValueError()
        if set(numbers) != {int(n) for n in re.findall(r"\[(\d+)\]", answer)}:
            raise ValueError()
        return answer.strip(), numbers, "answered"
    except (ValueError, TypeError, KeyError):
        raise WebSearchProblem(
            "invalid_web_answer", "联网回答的正文或来源校验失败，可重新生成", retryable=True
        ) from None

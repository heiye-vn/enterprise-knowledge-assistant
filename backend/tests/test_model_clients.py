import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.model_clients import ModelClient, ModelProblem


def settings(**kwargs):
    values = dict(
        _env_file=None,
        embedding_model="qwen3.7-text-embedding-flash",
        embedding_dimension=3,
        qwen_api_key=SecretStr("qwen-private"),
        qwen_base_url="https://qwen.test/compatible-mode/v1",
        qwen_llm_model="qwen3.8-max-0902",
        qwen_rerank_model="qwen3.7-text-rerank",
        monkey_api_key=SecretStr("monkey-private"),
        monkey_base_url="https://monkey.test",
        monkey_llm_model="gpt-6.1-sol",
    )
    values.update(kwargs)
    return Settings(**values)


def client(handler, **kwargs):
    return ModelClient(
        settings(**kwargs), http=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_embedding_uses_native_query_parameters_and_restores_input_order():
    def handler(request):
        assert (
            str(request.url)
            == "https://qwen.test/api/v1/services/embeddings/text-embedding/text-embedding"
        )
        assert request.headers["authorization"] == "Bearer qwen-private"
        body = json.loads(request.content)
        assert body["input"]["texts"] == ["报销", "请假"]
        assert body["parameters"] == {"dimension": 3, "text_type": "query"}
        return httpx.Response(
            200,
            json={
                "output": {
                    "embeddings": [
                        {"index": 1, "embedding": [0, 1, 0]},
                        {"index": 0, "embedding": [1, 0, 0]},
                    ]
                },
                "usage": {"total_tokens": 4},
            },
        )

    with client(handler) as models:
        batch = models.embed_texts(["报销", "请假"], text_type="query")
        assert batch.vectors == [[1, 0, 0], [0, 1, 0]]
        assert batch.usage["total_tokens"] == 4


def test_dashscope_text_index_response_preserves_the_original_input_mapping():
    entries = [
        {"text_index": 1, "embedding": [0, 1, 0], "type": "dense"},
        {"text_index": 0, "embedding": [1, 0, 0], "type": "dense"},
    ]
    with client(lambda _: httpx.Response(200, json={"output": {"embeddings": entries}})) as models:
        assert models.embed_texts(["报销", "请假"]).vectors == [[1, 0, 0], [0, 1, 0]]


def test_conflicting_embedding_index_fields_are_rejected():
    with (
        client(
            lambda _: httpx.Response(
                200,
                json={
                    "output": {
                        "embeddings": [{"index": 0, "text_index": 1, "embedding": [1, 0, 0]}]
                    }
                },
            )
        ) as models,
        pytest.raises(ModelProblem),
    ):
        models.embed_texts(["文本"])


@pytest.mark.parametrize(
    "entries",
    [
        [{"index": 0, "embedding": [1, 2]}],
        [{"index": 1, "embedding": [1, 2, 3]}],
        [{"index": 0, "embedding": [1, float("nan"), 3]}],
        [{"index": 0, "embedding": [0, 0, 0]}],
        [{"index": 0, "embedding": [1, 10**400, 0]}],
        [{"index": 0, "embedding": [1, 2, 3]}, {"index": 0, "embedding": [1, 2, 3]}],
    ],
)
def test_embedding_rejects_wrong_dimension_indexes_or_invalid_vector(entries):
    def handler(_):
        # Raw JSON permits exercising a non-finite provider value as well.
        return httpx.Response(200, content=json.dumps({"output": {"embeddings": entries}}).encode())

    with client(handler) as models, pytest.raises(ModelProblem) as caught:
        models.embed_texts(["原文"])
    assert caught.value.code == "invalid_model_response"


def test_rerank_retains_original_indexes_and_scores():
    def handler(request):
        assert request.url.path == "/api/v1/services/rerank/text-rerank/text-rerank"
        body = json.loads(request.content)
        assert body["parameters"] == {"top_n": 2, "return_documents": False}
        assert body["model"] == "qwen3.7-text-rerank"
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.97},
                        {"index": 0, "relevance_score": 0.03},
                    ]
                }
            },
        )

    with client(handler) as models:
        result = models.rerank("报销材料？", ["天气晴朗", "报销要发票"], top_n=2)
        assert [(x.index, x.score) for x in result.items] == [(1, 0.97), (0, 0.03)]


@pytest.mark.parametrize(
    "results",
    [
        [{"index": 2, "relevance_score": 0.8}],
        [{"index": 0, "relevance_score": 0.8}, {"index": 0, "relevance_score": 0.1}],
        [{"index": 0, "relevance_score": 1.1}],
    ],
)
def test_rerank_rejects_invalid_index_mapping_or_scores(results):
    with (
        client(lambda _: httpx.Response(200, json={"output": {"results": results}})) as models,
        pytest.raises(ModelProblem),
    ):
        models.rerank("问题", ["一", "二"], top_n=2)


def test_chat_provider_switch_keeps_each_key_and_model_at_its_own_endpoint():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request)
        if request.url.host == "qwen.test":
            assert request.url.path == "/compatible-mode/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer qwen-private"
            assert body["model"] == "qwen3.8-max-0902"
            assert body["enable_thinking"] is False
        else:
            assert request.url.host == "monkey.test"
            assert request.url.path == "/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer monkey-private"
            assert body["model"] == "gpt-6.1-sol"
            assert "enable_thinking" not in body
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 5},
            },
        )

    with client(handler, llm_provider="monkey") as models:
        assert models.complete([{"role": "user", "content": "test"}]).provider == "monkey"
        assert (
            models.complete([{"role": "user", "content": "test"}], provider="qwen").model
            == "qwen3.8-max-0902"
        )
    assert len(calls) == 2


def test_timeout_does_not_fallback_or_expose_credentials():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("monkey-private qwen-private", request=request)

    with client(handler, llm_provider="monkey") as models, pytest.raises(ModelProblem) as caught:
        models.complete([{"role": "user", "content": "test"}])
    assert len(calls) == 1 and calls[0].url.host == "monkey.test"
    assert caught.value.code == "model_unavailable"
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "model_auth"),
        (429, "model_rate_limited"),
        (500, "model_unavailable"),
        (400, "model_request_rejected"),
    ],
)
def test_provider_errors_are_distinct_and_redacted(status, code):
    with (
        client(
            lambda _: httpx.Response(status, json={"error": {"message": "qwen-private"}})
        ) as models,
        pytest.raises(ModelProblem) as caught,
    ):
        models.complete([{"role": "user", "content": "test"}])
    assert caught.value.code == code and "private" not in str(caught.value)


def sse(events):
    return (
        "\n\n".join("data: " + (json.dumps(e) if isinstance(e, dict) else e) for e in events)
        + "\n\n"
    )


def test_stream_yields_only_visible_content_and_requires_clean_termination():
    events = [
        {"choices": [{"delta": {"reasoning_content": "private reasoning"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "报销"}, "finish_reason": None}]},
        {"choices": [{"delta": {"content": "需要发票。"}, "finish_reason": "stop"}]},
        "[DONE]",
    ]
    with client(
        lambda _: httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text=sse(events)
        )
    ) as models:
        assert "".join(models.stream([{"role": "user", "content": "材料？"}])) == "报销需要发票。"
    with (
        client(lambda _: httpx.Response(200, text=sse(events[:-1]))) as models,
        pytest.raises(ModelProblem) as caught,
    ):
        list(models.stream([{"role": "user", "content": "材料？"}]))
    assert caught.value.code == "model_stream_incomplete"


def test_invalid_base_url_does_not_transmit_a_key():
    with (
        client(
            lambda _: pytest.fail("must not send credentials"),
            monkey_base_url="https://user:pass@monkey.test?api_key=private",
        ) as models,
        pytest.raises(ModelProblem),
    ):
        models.complete([{"role": "user", "content": "test"}], provider="monkey")


def test_malformed_error_code_is_controlled_and_never_leaks_response_body():
    with (
        client(
            lambda _: httpx.Response(200, json={"code": {"unexpected": "qwen-private"}})
        ) as models,
        pytest.raises(ModelProblem) as caught,
    ):
        models.complete([{"role": "user", "content": "test"}])
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("trust_env", [False, True])
def test_client_uses_explicit_network_policy(monkeypatch, trust_env):
    original = httpx.Client
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return original(transport=httpx.MockTransport(lambda _: httpx.Response(200)), **kwargs)

    monkeypatch.setattr("app.model_clients.httpx.Client", factory)
    with ModelClient(settings(model_trust_env=trust_env)):
        pass
    assert calls[0]["trust_env"] is trust_env
    assert calls[0].get("verify", True) is True
    assert calls[0]["follow_redirects"] is False


@pytest.mark.parametrize(
    "exception,kind",
    [
        (httpx.ConnectTimeout, "connect_timeout"),
        (httpx.ReadTimeout, "read_timeout"),
        (httpx.ProxyError, "proxy_error"),
        (httpx.ConnectError, "connect_error"),
        (httpx.RemoteProtocolError, "protocol_error"),
    ],
)
def test_network_diagnostics_identify_stage_without_logging_secrets(caplog, exception, kind):
    import logging

    def handler(request):
        raise exception("qwen-private prompt-secret proxy-password", request=request)

    with caplog.at_level(logging.INFO, logger="app.model_clients"):
        with client(handler) as models, pytest.raises(ModelProblem) as caught:
            models.complete([{"role": "user", "content": "prompt-secret"}])
    assert caught.value.retryable
    assert caught.value.transport_code == kind
    assert f"failure={kind}" in caplog.text and "operation=chat" in caplog.text
    assert "provider=qwen" in caplog.text and "elapsed_ms=" in caplog.text
    assert all(
        value not in caplog.text for value in ["qwen-private", "prompt-secret", "proxy-password"]
    )


def test_response_status_and_stream_failures_are_diagnostic(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="app.model_clients"):
        with client(lambda _: httpx.Response(429)) as models, pytest.raises(ModelProblem):
            models.rerank("query-secret", ["document-secret"])
    assert "operation=rerank" in caplog.text and "http_status=429" in caplog.text
    caplog.clear()

    def timeout(request):
        raise httpx.ReadTimeout("qwen-private", request=request)

    with caplog.at_level(logging.INFO, logger="app.model_clients"):
        with client(timeout) as models, pytest.raises(ModelProblem):
            list(models.stream([{"role": "user", "content": "query-secret"}]))
    assert "operation=chat_stream" in caplog.text and "failure=read_timeout" in caplog.text
    assert "qwen-private" not in caplog.text


def test_third_party_proxy_override_does_not_change_embedding_network(monkeypatch):
    original = httpx.Client
    routes = []

    def factory(**kwargs):
        trust = kwargs["trust_env"]

        def handler(request):
            routes.append((request.url.host, trust))
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}
            )

        return original(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("app.model_clients.httpx.Client", factory)
    with ModelClient(settings(monkey_model_trust_env=True)) as models:
        models.complete([{"role": "user", "content": "test"}], provider="qwen")
        models.complete([{"role": "user", "content": "test"}], provider="monkey")
    assert routes == [("qwen.test", False), ("monkey.test", True)]


def test_explicit_json_mode_is_sent_for_structured_answers():
    def handler(request):
        payload = json.loads(request.content)
        assert payload["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"answerable":false}'}}
                ]
            },
        )

    with client(handler) as models:
        assert (
            models.complete([{"role": "user", "content": "Return JSON"}], json_mode=True).content
            == '{"answerable":false}'
        )


def test_stream_cancel_closes_upstream_and_json_mode_does_not_buffer_tokens():
    closed = []

    class Body(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"first"},"finish_reason":null}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"second"},"finish_reason":null}]}\n\n'

        def close(self):
            closed.append(True)

    def handler(request):
        assert json.loads(request.content)["response_format"] == {"type": "json_object"}
        return httpx.Response(200, stream=Body())

    with client(handler) as models:
        stream = models.stream([{"role": "user", "content": "JSON answer"}], json_mode=True)
        assert next(stream) == "first"
        models.cancel_stream()
        assert list(stream) == [] and closed


def test_cancel_wakes_a_stream_blocked_waiting_for_the_next_tls_bytes():
    import ssl
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from pathlib import Path
    from threading import Event, Thread
    from time import sleep

    certificate = Path(__file__).parent / "fixtures/localhost-stream-test.pem"
    release, first, finished = Event(), Event(), Event()
    received, failures = [], []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n')
            self.wfile.flush()
            release.wait(5)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    http = httpx.Client(verify=ssl.create_default_context(cafile=str(certificate)), timeout=5)
    config = settings(qwen_base_url=f"https://127.0.0.1:{server.server_port}/v1")
    with ModelClient(config, http=http) as models:

        def consume():
            try:
                for token in models.stream([{"role": "user", "content": "test"}]):
                    received.append(token)
                    first.set()
            except Exception as error:
                failures.append(error)
            finally:
                finished.set()

        worker = Thread(target=consume, daemon=True)
        worker.start()
        try:
            assert first.wait(2)
            sleep(0.02)  # Let the reader enter the next TLS read.
            models.cancel_stream()
            assert finished.wait(1), "cancel must wake a TLS read without a provider timeout"
            assert received == ["first"] and not failures
        finally:
            release.set()
            worker.join(6)
            server.shutdown()
            server.server_close()

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.importing.mineru import MinerUClient
from app.importing.parsing import ParseError


def client(handler):
    settings = Settings(mineru_api_token=SecretStr("test-only-secret"))
    return MinerUClient(settings, http=httpx.Client(transport=httpx.MockTransport(handler)))


def test_submit_upload_poll_download_isolates_auth_and_matches_data_id():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "mineru.net":
            assert request.headers["authorization"] == "Bearer test-only-secret"
            if request.method == "POST":
                assert b'"data_id":"job-one"' in request.content
                return httpx.Response(
                    200,
                    json={
                        "code": 0,
                        "data": {
                            "batch_id": "batch",
                            "file_urls": [
                                "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?signature=private"
                            ],
                        },
                    },
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {"data_id": "another", "state": "failed"},
                            {
                                "data_id": "job-one",
                                "state": "done",
                                "full_zip_url": "https://cdn-mineru.openxlab.org.cn/result.zip",
                            },
                        ]
                    },
                },
            )
        assert "authorization" not in request.headers
        return httpx.Response(200, content=b"archive" if request.method == "GET" else b"")

    with client(handler) as mineru:
        remote = mineru.submit("制度.pdf", "job-one")
        mineru.upload(remote["upload_url"], b"original")
        result = mineru.poll(remote["batch_id"], "job-one")
        assert result["state"] == "done"
        assert mineru.download(result["full_zip_url"]) == b"archive"
    assert len(calls) == 4


@pytest.mark.parametrize(
    "url",
    [
        "http://mineru.net/file",
        "https://127.0.0.1/a",
        "https://mineru.net.evil.test/a",
        "https://user:pass@mineru.net/a",
        "https://mineru.net:8443/a",
    ],
)
def test_rejects_untrusted_resource_urls(url):
    with client(lambda _: pytest.fail("must not fetch")) as mineru, pytest.raises(ParseError):
        mineru.download(url)


def test_submit_timeout_is_uncertain_and_error_never_contains_credentials():
    def timeout(request):
        raise httpx.ReadTimeout("test-only-secret https://private-url", request=request)

    with client(timeout) as mineru, pytest.raises(ParseError) as caught:
        mineru.submit("doc.pdf", "id")
    assert caught.value.code == "mineru_submission_unknown"
    assert not caught.value.retryable
    assert "secret" not in str(caught.value)


def test_download_limit_and_redirects_are_rejected():
    with (
        client(lambda _: httpx.Response(200, content=b"12345")) as mineru,
        pytest.raises(ParseError),
    ):
        mineru.download("https://cdn-mineru.openxlab.org.cn/a", max_bytes=4)
    with (
        client(lambda _: httpx.Response(302, headers={"location": "http://localhost/"})) as mineru,
        pytest.raises(ParseError),
    ):
        mineru.download("https://cdn-mineru.openxlab.org.cn/a")


def test_authentication_error_is_nonretryable_and_redacted():
    with (
        client(
            lambda _: httpx.Response(200, json={"code": "A0202", "msg": "test-only-secret"})
        ) as mineru,
        pytest.raises(ParseError) as caught,
    ):
        mineru.poll("batch", "id")
    assert not caught.value.retryable
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize("inherit_proxy", [False, True])
def test_default_client_uses_explicit_network_mode_for_resource_download(
    monkeypatch, inherit_proxy
):
    factory = httpx.Client
    options = []

    def make_client(**kwargs):
        options.append(kwargs)
        return factory(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"archive")),
            **kwargs,
        )

    monkeypatch.setattr("app.importing.mineru.httpx.Client", make_client)
    settings = Settings(model_trust_env=inherit_proxy)
    with MinerUClient(settings) as mineru:
        assert mineru.download("https://cdn-mineru.openxlab.org.cn/result.zip") == b"archive"
    assert options[0]["trust_env"] is inherit_proxy

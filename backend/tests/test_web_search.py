import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.tools.web_search import TavilySearch, WebSearchProblem


def config():
    return Settings(_env_file=None, tavily_api_key=SecretStr("private-search-key"))


def test_tavily_is_one_bounded_public_query_and_deduplicates_safe_results():
    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        assert body["query"] == "Python release" and body["max_results"] == 5
        assert body["search_depth"] == "basic" and body["include_raw_content"] is False
        assert "history" not in body and "documents" not in body
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://www.python.org/a",
                        "title": "Release",
                        "content": "A release",
                        "score": 0.9,
                    },
                    {"url": "https://www.python.org/a", "title": "duplicate", "content": "Again"},
                    {"url": "javascript:alert(1)", "title": "bad", "content": "bad"},
                    {"url": "http://127.0.0.1/private", "title": "local", "content": "bad"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        result = TavilySearch(config(), http=http).search("Python release")
    assert len(calls) == 1 and len(result["results"]) == 1
    assert (
        result["results"][0]["number"] == 1
        and result["results"][0]["url"] == "https://www.python.org/a"
    )
    assert result["provider"] == "tavily" and result["queried_at"]


@pytest.mark.parametrize(
    "status,code",
    [(401, "web_search_auth"), (429, "web_search_rate_limited"), (503, "web_search_unavailable")],
)
def test_tavily_failure_is_explicit_without_retry_or_secret_leak(status, code):
    calls = []

    def handler(request):
        calls.append(True)
        return httpx.Response(status, text="private-search-key")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(WebSearchProblem) as error:
            TavilySearch(config(), http=http).search("public query")
    assert error.value.code == code and "private-search-key" not in str(error.value)
    assert len(calls) == 1


def test_tavily_empty_and_timeout_are_not_fabricated_results():
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"results": []}))
    ) as http:
        assert TavilySearch(config(), http=http).search("public")["results"] == []

    def timeout(request):
        raise httpx.ReadTimeout("private-search-key", request=request)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as http:
        with pytest.raises(WebSearchProblem, match="超时"):
            TavilySearch(config(), http=http).search("public")


def test_web_answer_requires_real_citation_numbers_and_matching_draft():
    from app.tools.web_search import validate_web_answer

    sources = [
        {"number": 1, "url": "https://www.python.org/a", "title": "Release", "content": "released"}
    ]
    assert validate_web_answer(
        '{"answerable":true,"answer":"Released.[1]","citations":[{"source":1}]}', sources
    ) == ("Released.[1]", [1], "answered")
    with pytest.raises(WebSearchProblem):
        validate_web_answer(
            '{"answerable":true,"answer":"False.[9]","citations":[{"source":9}]}', sources
        )

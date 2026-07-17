"""A bulk enrichment run on a free tier hits the per-minute rate limit as a
matter of course, so backing off and retrying is the normal path -- not an
error path. These pin which failures are worth waiting out.
"""
import httpx
import pytest

from app.llm.openai_compat import OpenAICompatProvider, _is_retryable


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(f"{status}", request=request, response=response)


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_rate_limits_and_server_errors_are_retried(status):
    assert _is_retryable(_http_error(status)) is True


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_are_not_retried(status):
    # A bad key or malformed request will fail identically forever -- retrying
    # just burns the rate limit that a later article needs.
    assert _is_retryable(_http_error(status)) is False


def test_transport_failures_are_retried():
    assert _is_retryable(httpx.ConnectError("dns")) is True
    assert _is_retryable(httpx.TimeoutException("slow")) is True


def test_unrelated_exceptions_are_not_retried():
    assert _is_retryable(ValueError("bad json")) is False


async def test_retry_decorator_keeps_the_method_awaitable(monkeypatch):
    """tenacity wraps the coroutine; make sure a plain success still works."""
    provider = OpenAICompatProvider("https://example.com/v1", "llama-3.3-70b-versatile", "k")

    async def fake_post(self, url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={"choices": [{"message": {"content": " Merhaba "}}]},
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    assert await provider._generate("selam") == "Merhaba"

"""`http.py`: the one client, and the retry policy every service shares."""

from __future__ import annotations

import httpx
from support import _http_answering, case

from ponos import http as http_module


@case
def every_service_is_asked_again_as_notion_always_was():
    """GitHub, OpenRouter, the channels, the pictures: one policy, Notion's.

    A read is asked again after a 5xx or a silence, a POST only when it was
    refused before anything was done — a 429, a connection that never opened.
    And what keeps failing comes back as the last answer, or `Unanswered`.
    """
    seen: list[str] = []
    script: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.method)
        assert request.headers["User-Agent"] == http_module.USER_AGENT
        answer = script.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    with _http_answering(handler) as pauses:
        script[:] = [httpx.Response(503), httpx.ReadTimeout("slow"), httpx.Response(200, text="ok")]
        answer = http_module.send("github", "GET", "https://example.test/x")
        assert (answer.status, answer.body) == (200, b"ok"), answer
        assert seen == ["GET"] * 3 and pauses == [1.5, 3.0], (seen, pauses)

        seen.clear()
        script[:] = [httpx.Response(503), httpx.Response(200)]
        assert http_module.send("channels", "POST", "https://example.test/x").status == 503
        assert seen == ["POST"], "a message posted twice is two messages"

        seen.clear()
        pauses.clear()
        script[:] = [httpx.Response(429, headers={"Retry-After": "5"}), httpx.Response(200)]
        assert http_module.send("channels", "POST", "https://example.test/x").status == 200
        assert pauses == [5.0], pauses

        script[:] = [httpx.ReadTimeout("slow")]
        try:
            http_module.send("channels", "POST", "https://example.test/x")
        except http_module.Unanswered as error:
            assert "may have been applied" in str(error) and not error.offline, error
        else:
            raise AssertionError("a POST that may have landed was taken for an answer")

        script[:] = [httpx.ConnectError("[Errno -2] Name or service not known")] * 2
        try:
            http_module.send("images", "GET", "https://example.test/x", attempts=2)
        except http_module.Unanswered as error:
            assert error.offline and "gave up after 2 attempts" in str(error), error
        else:
            raise AssertionError("a host that does not exist answered")

        script[:] = [httpx.Response(200, content=b"x" * 100)]
        answer = http_module.send("images", "GET", "https://example.test/x", limit=10)
        assert 10 < len(answer.body) <= 100 and answer.kind == "text/plain", answer

from __future__ import annotations

from typing import Any

import pytest
import requests

from guildbridge.http import HttpClient, HttpError, HttpTransportError, retry_delay_seconds, sanitize_text


class FakeResponse:
    def __init__(
        self,
        status_code: int,
        *,
        text: str = "",
        body: Any = None,
        headers: dict[str, str] | None = None,
    ):
        self.status_code = status_code
        self.text = text
        self._body = body
        self.headers = headers or {}
        self.content = text.encode("utf-8") if text else (b"{}" if body is not None else b"")

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = responses
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_http_retries_retryable_status_and_returns_json() -> None:
    session = FakeSession(
        [
            FakeResponse(503, text="temporary"),
            FakeResponse(200, body={"ok": True}),
        ]
    )
    sleeps: list[float] = []
    client = HttpClient("https://api.example", max_retries=1, retry_sleep=sleeps.append)
    client.session = session  # type: ignore[assignment]

    assert client.get("/thing") == {"ok": True}
    assert len(session.calls) == 2
    assert len(sleeps) == 1


def test_http_retries_transport_errors_before_failing() -> None:
    session = FakeSession(
        [
            requests.Timeout("Authorization: Bot super-secret"),
            requests.ConnectionError("token=abc123"),
        ]
    )
    client = HttpClient("https://api.example", max_retries=1, retry_sleep=lambda _: None)
    client.session = session  # type: ignore[assignment]

    with pytest.raises(HttpTransportError) as exc_info:
        client.get("/thing")

    assert exc_info.value.attempts == 2
    assert "abc123" not in str(exc_info.value)
    assert "[redacted]" in str(exc_info.value)


def test_http_error_sanitizes_response_text() -> None:
    session = FakeSession([FakeResponse(400, text='{"access_token":"secret-token"}')])
    client = HttpClient("https://api.example", max_retries=0)
    client.session = session  # type: ignore[assignment]

    with pytest.raises(HttpError) as exc_info:
        client.get("/thing")

    assert "secret-token" not in str(exc_info.value)
    assert "[redacted]" in str(exc_info.value)


def test_retry_delay_uses_retry_after_header() -> None:
    response = FakeResponse(429, headers={"Retry-After": "2.5"})
    assert retry_delay_seconds(0, response) == 2.5


def test_sanitize_text_redacts_common_secret_shapes() -> None:
    text = "Authorization: Bearer abc.def token='xyz' session: qqq"
    sanitized = sanitize_text(text)
    assert "abc.def" not in sanitized
    assert "xyz" not in sanitized
    assert "qqq" not in sanitized
    assert sanitized.count("[redacted]") == 3

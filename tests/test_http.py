from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from guildbridge.http import (
    HttpClient,
    HttpError,
    HttpTransportError,
    retry_delay_seconds,
    sanitize_response_text,
    sanitize_text,
)


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


def test_http_error_compacts_html_response_text() -> None:
    body = "<!DOCTYPE html><html><head><title>401 Unauthorized</title></head><body><h1>401 Unauthorized</h1></body></html>"

    assert sanitize_response_text(body) == "401 Unauthorized 401 Unauthorized"


def test_http_post_form_sends_urlencoded_body() -> None:
    session = FakeSession([FakeResponse(200, body={"ok": True})])
    client = HttpClient("https://api.example", max_retries=0)
    client.session = session  # type: ignore[assignment]

    assert client.post_form("/thing", form_body={"name": "general"}) == {"ok": True}
    assert session.calls[0]["data"] == {"name": "general"}
    assert session.calls[0]["json"] is None
    assert session.calls[0]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


def test_http_post_file_sends_multipart_without_json_content_type(tmp_path: Path) -> None:
    upload = tmp_path / "upload.txt"
    upload.write_text("hello", encoding="utf-8")
    session = FakeSession([FakeResponse(200, body={"id": "file-1"})])
    client = HttpClient("https://api.example", max_retries=0)
    client.session = session  # type: ignore[assignment]

    assert client.post_file("/attachments", file_path=upload, headers={"X-Session-Token": "token"}) == {"id": "file-1"}
    assert session.calls[0]["data"] == {}
    assert "files" in session.calls[0]
    assert session.calls[0]["json"] is None
    assert "Content-Type" not in session.calls[0]["headers"]
    assert session.calls[0]["headers"]["X-Session-Token"] == "token"


def test_http_post_files_sends_indexed_multipart_fields(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    session = FakeSession([FakeResponse(200, body={"ok": True})])
    client = HttpClient("https://api.example", max_retries=0)
    client.session = session  # type: ignore[assignment]

    assert client.post_files("/messages", file_paths=[first, second], form_body={"payload_json": "{}"}) == {"ok": True}
    assert session.calls[0]["data"] == {"payload_json": "{}"}
    assert sorted(session.calls[0]["files"]) == ["files[0]", "files[1]"]
    assert session.calls[0]["json"] is None
    assert "Content-Type" not in session.calls[0]["headers"]


def test_retry_delay_uses_retry_after_header() -> None:
    response = FakeResponse(429, headers={"Retry-After": "2.5"})
    assert retry_delay_seconds(0, response) == 2.5  # type: ignore[arg-type]


def test_sanitize_text_redacts_common_secret_shapes() -> None:
    text = "Authorization: Bearer abc.def token='xyz' session: qqq"
    sanitized = sanitize_text(text)
    assert "abc.def" not in sanitized
    assert "xyz" not in sanitized
    assert "qqq" not in sanitized
    assert sanitized.count("[redacted]") == 3

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_USER_AGENT = "GuildBridge/0.1 (+https://github.com/Yunushan/guildbridge)"
MAX_RETRY_DELAY_SECONDS = 30.0
TOKEN_PATTERNS = (
    re.compile(r"(Authorization:\s*(?:Bot|Bearer)?\s*)[^\s,;]+", re.IGNORECASE),
    re.compile(r"((?:token|access_token|bot_token|session|secret)[\"'=:\s]+)[^\"'\s,;}]+", re.IGNORECASE),
)


@dataclass
class HttpError(RuntimeError):
    method: str
    url: str
    status_code: int
    text: str
    attempts: int = 1

    def __str__(self) -> str:
        return f"{self.method} {self.url} failed with {self.status_code} after {self.attempts} attempt(s): {self.text[:500]}"


@dataclass
class HttpTransportError(RuntimeError):
    method: str
    url: str
    message: str
    attempts: int

    def __str__(self) -> str:
        return f"{self.method} {self.url} failed after {self.attempts} attempt(s): {self.message}"


class HttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        auth_scheme: str = "Bot",
        timeout: int = 30,
        max_retries: int = 5,
        user_agent: str = DEFAULT_USER_AGENT,
        retry_sleep: Any = time.sleep,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self.auth_scheme = auth_scheme
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_sleep = retry_sleep
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent or DEFAULT_USER_AGENT})

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            if self.auth_scheme:
                headers["Authorization"] = f"{self.auth_scheme} {self.token}"
            else:
                headers["Authorization"] = self.token
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> Any:
        if json_body is not None and form_body is not None:
            raise ValueError("Use either json_body or form_body, not both.")
        url = path if path.startswith("http://") or path.startswith("https://") else urljoin(self.base_url, path.lstrip("/"))
        method_upper = method.upper()
        max_retries = self.max_retries if retries is None else max(0, retries)
        attempts = max_retries + 1
        last_transport_error: requests.RequestException | None = None
        request_headers = headers
        if form_body is not None:
            request_headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        for attempt in range(attempts):
            try:
                resp = self.session.request(
                    method_upper,
                    url,
                    json=json_body,
                    data=form_body,
                    params=params,
                    headers=self.headers(request_headers),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_transport_error = exc
                if attempt < max_retries:
                    self._sleep_before_retry(attempt, None)
                    continue
                raise HttpTransportError(method_upper, url, sanitize_text(str(exc)), attempt + 1) from exc

            if resp.status_code in RETRYABLE_STATUS_CODES and attempt < max_retries:
                self._sleep_before_retry(attempt, resp)
                continue
            if 200 <= resp.status_code < 300:
                if not resp.content:
                    return None
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return resp.text
            raise HttpError(method_upper, url, resp.status_code, sanitize_text(resp.text), attempt + 1)
        if last_transport_error is not None:
            raise HttpTransportError(method_upper, url, sanitize_text(str(last_transport_error)), attempts) from last_transport_error
        raise AssertionError("unreachable")

    def _sleep_before_retry(self, attempt: int, response: requests.Response | None) -> None:
        delay = retry_delay_seconds(attempt, response)
        self.retry_sleep(delay)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def post_form(self, path: str, form_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("POST", path, form_body=form_body, **kwargs)

    def patch(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, json_body=json_body, **kwargs)

    def patch_form(self, path: str, form_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, form_body=form_body, **kwargs)

    def put(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)


def sanitize_text(text: str) -> str:
    sanitized = text
    for pattern in TOKEN_PATTERNS:
        sanitized = pattern.sub(r"\1[redacted]", sanitized)
    return sanitized


def retry_delay_seconds(attempt: int, response: requests.Response | None = None) -> float:
    if response is not None:
        retry_header = response.headers.get("Retry-After")
        if retry_header:
            try:
                return min(float(retry_header), MAX_RETRY_DELAY_SECONDS)
            except ValueError:
                pass
        try:
            body = response.json()
            retry_after = body.get("retry_after")
            if retry_after is not None:
                return min(float(retry_after), MAX_RETRY_DELAY_SECONDS)
        except Exception:
            pass
    base = min(2.0 ** attempt, MAX_RETRY_DELAY_SECONDS)
    jitter = random.uniform(0, min(0.25, base / 4))
    return min(base + jitter, MAX_RETRY_DELAY_SECONDS)

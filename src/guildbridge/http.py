from __future__ import annotations

import html
import ipaddress
import json
import os
import random
import re
import time
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_USER_AGENT = "GuildBridge/0.1 (+https://github.com/Yunushan/guildbridge)"
MAX_RETRY_DELAY_SECONDS = 30.0
TOKEN_PATTERNS = (
    re.compile(r"(Authorization:\s*(?:Bot|Bearer)?\s*)[^\s,;]+", re.IGNORECASE),
    re.compile(r"((?:token|access_token|bot_token|session|secret)[\"'=:\s]+)[^\"'\s,;}&]+", re.IGNORECASE),
)
QUERY_SECRET_PATTERN = re.compile(
    r"(?P<prefix>[?&;](?:access(?:[_-]?token)?|api[_-]?key|auth(?:orization)?|bot[_-]?token|code|key|password|secret|session(?:[_-]?token)?|token)=)[^&#;\s]*",
    re.IGNORECASE,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass
class HttpError(RuntimeError):
    method: str
    url: str
    status_code: int
    text: str
    attempts: int = 1

    def __str__(self) -> str:
        return (
            f"{self.method} {sanitize_url(self.url)} failed with {self.status_code} after {self.attempts} attempt(s): "
            f"{sanitize_text(self.text)[:500]}"
        )


@dataclass
class HttpTransportError(RuntimeError):
    method: str
    url: str
    message: str
    attempts: int

    def __str__(self) -> str:
        return f"{self.method} {sanitize_url(self.url)} failed after {self.attempts} attempt(s): {sanitize_text(self.message)}"


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
        allow_insecure_http: bool | None = None,
        retry_sleep: Any = time.sleep,
    ):
        self.base_url = base_url.rstrip("/") + "/"
        self.allow_insecure_http = (
            allow_insecure_http
            if allow_insecure_http is not None
            else os.environ.get("GUILDBRIDGE_ALLOW_INSECURE_HTTP", "").strip().lower() in {"1", "true", "yes", "on"}
        )
        self._assert_secure_url(self.base_url)
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
        data_body: bytes | str | None = None,
        files: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> Any:
        if json_body is not None and (form_body is not None or data_body is not None or files is not None):
            raise ValueError("Use either json_body or form_body/data_body/files, not multiple body types.")
        if data_body is not None and (form_body is not None or files is not None):
            raise ValueError("Use either data_body or form_body/files, not both.")
        url = path if path.startswith("http://") or path.startswith("https://") else urljoin(self.base_url, path.lstrip("/"))
        self._assert_secure_url(url)
        method_upper = method.upper()
        max_retries = self.max_retries if retries is None else max(0, retries)
        attempts = max_retries + 1
        last_transport_error: requests.RequestException | None = None
        request_headers = headers
        if form_body is not None:
            request_headers = {"Content-Type": "application/x-www-form-urlencoded", **(headers or {})}
        if files is not None:
            request_headers = dict(headers or {})
        for attempt in range(attempts):
            merged_headers = self.headers(request_headers)
            if files is not None:
                # requests must generate the multipart boundary itself.
                merged_headers.pop("Content-Type", None)
            try:
                resp = self.session.request(
                    method_upper,
                    url,
                    json=json_body,
                    data=data_body if data_body is not None else form_body,
                    files=files,
                    params=params,
                    headers=merged_headers,
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
            raise HttpError(method_upper, url, resp.status_code, sanitize_response_text(resp.text), attempt + 1)
        if last_transport_error is not None:
            raise HttpTransportError(method_upper, url, sanitize_text(str(last_transport_error)), attempts) from last_transport_error
        raise AssertionError("unreachable")

    def _sleep_before_retry(self, attempt: int, response: requests.Response | None) -> None:
        delay = retry_delay_seconds(attempt, response)
        self.retry_sleep(delay)

    def _assert_secure_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"Provider API URL must be an absolute HTTP(S) URL: {sanitize_url(url)!r}")
        if parsed.scheme == "http" and not _is_loopback_host(parsed.hostname) and not self.allow_insecure_http:
            raise ValueError(
                "Refusing a non-loopback HTTP provider API endpoint because credentials could be exposed. "
                "Use HTTPS, or set GUILDBRIDGE_ALLOW_INSECURE_HTTP=1 only for a controlled legacy deployment."
            )

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def post_form(self, path: str, form_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("POST", path, form_body=form_body, **kwargs)

    def post_raw(self, path: str, data_body: bytes | str, **kwargs: Any) -> Any:
        return self.request("POST", path, data_body=data_body, **kwargs)

    def post_file(
        self,
        path: str,
        *,
        file_path: str | Path,
        field_name: str = "file",
        form_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> Any:
        resolved = Path(file_path)
        with resolved.open("rb") as handle:
            return self.request(
                "POST",
                path,
                form_body=form_body or {},
                files={field_name: (resolved.name, handle)},
                headers=headers,
                **kwargs,
            )

    def post_files(
        self,
        path: str,
        *,
        file_paths: Sequence[str | Path],
        field_prefix: str = "files",
        form_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        indexed_fields: bool = True,
        **kwargs: Any,
    ) -> Any:
        with ExitStack() as stack:
            files: dict[str, Any] = {}
            for index, raw_path in enumerate(file_paths):
                resolved = Path(raw_path)
                field_name = f"{field_prefix}[{index}]" if indexed_fields else field_prefix
                if not indexed_fields and field_name in files:
                    field_name = f"{field_prefix}{index}"
                files[field_name] = (resolved.name, stack.enter_context(resolved.open("rb")))
            return self.request(
                "POST",
                path,
                form_body=form_body or {},
                files=files,
                headers=headers,
                **kwargs,
            )

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


def sanitize_url(url: str) -> str:
    """Redact credential-shaped query values without changing a safe URL's structure."""
    return sanitize_text(QUERY_SECRET_PATTERN.sub(r"\g<prefix>[redacted]", url))


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.strip("[]").lower().rstrip(".")
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def sanitize_response_text(text: str) -> str:
    sanitized = sanitize_text(text)
    if "<html" not in sanitized.lower() and "<!doctype" not in sanitized.lower():
        return sanitized
    plain = html.unescape(HTML_TAG_PATTERN.sub(" ", sanitized))
    return WHITESPACE_PATTERN.sub(" ", plain).strip()


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
        except ValueError:
            pass
    base = min(2.0 ** attempt, MAX_RETRY_DELAY_SECONDS)
    # This jitter only avoids synchronized retries; it is not used for security.
    jitter = random.uniform(0, min(0.25, base / 4))  # noqa: S311
    return min(base + jitter, MAX_RETRY_DELAY_SECONDS)

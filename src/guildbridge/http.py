from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests


@dataclass
class HttpError(RuntimeError):
    method: str
    url: str
    status_code: int
    text: str

    def __str__(self) -> str:
        return f"{self.method} {self.url} failed with {self.status_code}: {self.text[:500]}"


class HttpClient:
    def __init__(self, base_url: str, *, token: str | None = None, auth_scheme: str = "Bot", timeout: int = 30):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self.auth_scheme = auth_scheme
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GuildBridge/0.1 (+https://github.com/your-org/guildbridge)"})

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
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        retries: int = 3,
    ) -> Any:
        url = path if path.startswith("http://") or path.startswith("https://") else urljoin(self.base_url, path.lstrip("/"))
        for attempt in range(retries + 1):
            resp = self.session.request(
                method.upper(),
                url,
                json=json_body,
                params=params,
                headers=self.headers(headers),
                timeout=self.timeout,
            )
            if resp.status_code == 429 and attempt < retries:
                delay = 1.0
                try:
                    body = resp.json()
                    delay = float(body.get("retry_after", delay))
                except Exception:
                    retry_header = resp.headers.get("Retry-After")
                    if retry_header:
                        try:
                            delay = float(retry_header)
                        except ValueError:
                            pass
                time.sleep(min(delay, 30.0))
                continue
            if 200 <= resp.status_code < 300:
                if not resp.content:
                    return None
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return resp.text
            raise HttpError(method.upper(), url, resp.status_code, resp.text)
        raise AssertionError("unreachable")

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("POST", path, json_body=json_body, **kwargs)

    def patch(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, json_body=json_body, **kwargs)

    def put(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, json_body=json_body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

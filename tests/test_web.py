from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from guildbridge.gui_commands import CommandResult
from guildbridge.web import (
    APPLY_CONFIRMATION,
    AUTH_FIELD,
    AUTH_HEADER,
    CSRF_FIELD,
    GuildBridgeWebHandler,
    build_web_args,
    render_page,
    serve,
    validate_lan_auth_token,
)


@contextmanager
def running_web_server(*, auth_token: str = "lan-secret", require_auth: bool = True) -> Iterator[str]:
    old_state = (
        GuildBridgeWebHandler.csrf_token,
        GuildBridgeWebHandler.auth_token,
        GuildBridgeWebHandler.require_auth,
        GuildBridgeWebHandler.allow_lan,
        GuildBridgeWebHandler.max_body_bytes,
    )
    GuildBridgeWebHandler.csrf_token = "csrf-secret"
    GuildBridgeWebHandler.auth_token = auth_token
    GuildBridgeWebHandler.require_auth = require_auth
    GuildBridgeWebHandler.allow_lan = True
    GuildBridgeWebHandler.max_body_bytes = 64 * 1024
    server = ThreadingHTTPServer(("127.0.0.1", 0), GuildBridgeWebHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        raw_host = server.server_address[0]
        host = raw_host.decode("ascii") if isinstance(raw_host, bytes) else str(raw_host)
        port = int(server.server_address[1])
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        (
            GuildBridgeWebHandler.csrf_token,
            GuildBridgeWebHandler.auth_token,
            GuildBridgeWebHandler.require_auth,
            GuildBridgeWebHandler.allow_lan,
            GuildBridgeWebHandler.max_body_bytes,
        ) = old_state


def test_build_web_migrate_args() -> None:
    args = build_web_args(
        {
            "action": ["migrate"],
            "provider_from": ["discord"],
            "provider_to": ["matrix", "rocket.chat"],
            "source_id": ["123"],
            "target_name": ["Target Space"],
            "plan_out": ["plan.json"],
            "plan_in": ["reviewed.plan.json"],
            "journal_out": ["journal.json"],
            "resume_journal": ["failed-journal.json"],
            "redact": ["on"],
            "force_invalid_template": ["on"],
        }
    )
    assert args[:7] == ["migrate", "--from", "discord", "--to", "matrix", "--to", "rocket.chat"]
    assert "--source-id" in args
    assert args[args.index("--plan-in") + 1] == "reviewed.plan.json"
    assert args[args.index("--journal-out") + 1] == "journal.json"
    assert args[args.index("--resume-journal") + 1] == "failed-journal.json"
    assert "--redact" in args
    assert "--force-invalid-template" in args


def test_build_web_platform_args() -> None:
    assert build_web_args({"action": ["platforms"]}) == ["platforms", "--check"]


def test_render_page_includes_mobile_platforms() -> None:
    page = render_page(csrf_token="test-token", auth_token="lan-token")
    assert "Android" in page
    assert "Apple iOS" in page
    assert "Run Migrate" in page
    assert "Desktop GUI" in page
    assert "browser client supported" in page
    assert "Reviewed plan input" in page
    assert "Journal output" in page
    assert "Resume journal" in page
    assert "Force invalid template after review" in page
    assert f'name="{CSRF_FIELD}" value="test-token"' in page
    assert f'name="{AUTH_FIELD}" value="lan-token"' in page
    assert f"Type {APPLY_CONFIRMATION}" in page
    assert 'select name="provider_to" multiple' in page


def test_render_page_has_mobile_layout_contracts() -> None:
    page = render_page(csrf_token="test-token", auth_token="lan-token")

    assert 'class="tool-nav"' in page
    assert 'aria-label="GuildBridge tools"' in page
    assert 'href="#migrate"' in page
    assert "@media (max-width: 720px)" in page
    assert "min-height: 44px" in page
    assert 'class="table-wrap" role="region"' in page
    assert 'autocomplete="off"' in page
    assert 'autocapitalize="off"' in page
    assert 'spellcheck="false"' in page
    assert 'aria-label="Runtime readiness"' in page


def test_render_page_marks_result_state() -> None:
    failed = CommandResult(("providers",), ("guildbridge", "providers"), 2, "", "bad", 0.25)
    failed_page = render_page(failed, csrf_token="test-token")

    assert "output--failed" in failed_page
    assert "<h2>Failed</h2>" in failed_page
    assert "Exit code" in failed_page

    timed_out = CommandResult(("providers",), ("guildbridge", "providers"), 124, "", "late", 1.0, timed_out=True)
    timed_out_page = render_page(timed_out, csrf_token="test-token")

    assert "output--timeout" in timed_out_page
    assert "<h2>Timed out</h2>" in timed_out_page


def test_web_apply_requires_typed_confirmation() -> None:
    with pytest.raises(ValueError, match="without typing"):
        build_web_args(
            {
                "action": ["import"],
                "provider_to": ["discord"],
                "file": ["community.json"],
                "apply": ["on"],
            }
        )

    args = build_web_args(
        {
            "action": ["import"],
            "provider_to": ["discord"],
            "file": ["community.json"],
            "apply": ["on"],
            "confirm_apply": [APPLY_CONFIRMATION],
        }
    )
    assert "--apply" in args
    assert args[args.index("--confirm-apply") + 1] == APPLY_CONFIRMATION


def test_lan_auth_helper_rejects_bad_tokens() -> None:
    validate_lan_auth_token("secret", "secret")
    with pytest.raises(ValueError, match="auth token"):
        validate_lan_auth_token("wrong", "secret")


def test_lan_auth_rejects_get_without_token() -> None:
    with running_web_server() as base_url:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(base_url, timeout=5)  # noqa: S310

    assert exc_info.value.code == 401
    assert exc_info.value.headers["X-Frame-Options"] == "DENY"
    assert exc_info.value.headers["Cache-Control"] == "no-store"


def test_lan_auth_allows_get_with_token() -> None:
    with running_web_server(auth_token="secret-token") as base_url:
        response = urlopen(f"{base_url}/?{AUTH_FIELD}=secret-token", timeout=5)  # noqa: S310
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert response.headers["Content-Security-Policy"]
    assert f'name="{AUTH_FIELD}" value="secret-token"' in body


def test_lan_auth_rejects_post_without_token() -> None:
    data = urlencode({CSRF_FIELD: "csrf-secret", "action": "platforms"}).encode("utf-8")
    with running_web_server() as base_url:
        request = Request(f"{base_url}/run", data=data, method="POST")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)  # noqa: S310

    assert exc_info.value.code == 401


def test_lan_auth_allows_post_header_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "guildbridge.web.run_cli_args",
        lambda args: CommandResult(tuple(args), ("guildbridge", *args), 0, "ok", "", 0.0),
    )
    data = urlencode({CSRF_FIELD: "csrf-secret", "action": "platforms"}).encode("utf-8")
    with running_web_server(auth_token="secret-token") as base_url:
        request = Request(f"{base_url}/run", data=data, method="POST", headers={AUTH_HEADER: "secret-token"})
        response = urlopen(request, timeout=5)  # noqa: S310
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert "guildbridge platforms --check" in body


def test_web_in_process_errors_include_recovery_guidance() -> None:
    data = urlencode(
        {
            CSRF_FIELD: "csrf-secret",
            "action": "import",
            "provider_to": "discord",
            "file": "community.json",
            "apply": "on",
        }
    ).encode("utf-8")
    with running_web_server(auth_token="secret-token") as base_url:
        request = Request(f"{base_url}/run", data=data, method="POST", headers={AUTH_HEADER: "secret-token"})
        response = urlopen(request, timeout=5)  # noqa: S310
        body = response.read().decode("utf-8")

    assert response.status == 200
    assert "guildbridge: error:" in body
    assert "recovery:" in body
    assert "--plan-in" in body


def test_serve_does_not_echo_configured_lan_token(monkeypatch: pytest.MonkeyPatch, capsys) -> None:  # type: ignore[no-untyped-def]
    class FakeServer:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def serve_forever(self) -> None:
            raise RuntimeError("stop")

    monkeypatch.setattr("guildbridge.web.ThreadingHTTPServer", FakeServer)

    with pytest.raises(RuntimeError, match="stop"):
        serve("0.0.0.0", allow_lan=True, auth_token="super-secret-token")

    out = capsys.readouterr().out
    assert "super-secret-token" not in out
    assert f"?{AUTH_FIELD}=<token>" in out


def test_web_refuses_non_loopback_without_lan_opt_in() -> None:
    with pytest.raises(ValueError, match="non-loopback"):
        serve("0.0.0.0")


def test_web_rejects_tiny_request_limit() -> None:
    with pytest.raises(ValueError, match="at least 1024"):
        serve(max_body_bytes=100)

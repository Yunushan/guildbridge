from __future__ import annotations

import argparse
import html
import ipaddress
import os
import secrets
import ssl
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from guildbridge import __version__
from guildbridge.diagnostics import format_error_report
from guildbridge.gui_commands import (
    CommandResult,
    build_content_export_args,
    build_content_import_args,
    build_content_migrate_args,
    build_export_args,
    build_import_args,
    build_migrate_args,
    build_redact_args,
    build_validate_args,
    command_preview,
    run_cli_args,
)
from guildbridge.platforms import SUPPORTED_PLATFORMS, runtime_check
from guildbridge.providers import provider_names
from guildbridge.safety import APPLY_CONFIRMATION

CSRF_FIELD = "csrf_token"
AUTH_FIELD = "auth_token"
AUTH_HEADER = "X-GuildBridge-Auth"
AUTH_COOKIE = "guildbridge_session"
DEFAULT_MAX_BODY_BYTES = 64 * 1024
THEMES = ("light", "dark")
THEME_VALUES = {"light": "light", "dark": "dark"}


def _first(form: Mapping[str, list[str]], key: str, default: str = "") -> str:
    values = form.get(key)
    if not values:
        return default
    return values[0]


def _values(form: Mapping[str, list[str]], key: str, default: str = "") -> list[str]:
    values = [value.strip() for value in form.get(key, []) if value.strip()]
    if values:
        return values
    return [default] if default else []


def _checked(form: Mapping[str, list[str]], key: str) -> bool:
    return key in form


def _theme(value: str) -> str:
    return THEME_VALUES.get(value.strip().lower(), "light")


def _create_tls_server_context() -> ssl.SSLContext:
    """Create a server context that rejects obsolete TLS protocol versions."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _is_loopback_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value.lower() in {"localhost", "localhost.localdomain"}


def _is_loopback_host(value: str) -> bool:
    if value in {"", "localhost"}:
        return True
    return _is_loopback_address(value)


def _auth_token_valid(provided: str, expected: str) -> bool:
    return bool(expected) and secrets.compare_digest(provided, expected)


def _auth_input(_auth_token: str) -> str:
    # LAN authentication is stored in an HttpOnly session cookie, never in HTML.
    return ""


def _session_cookie(auth_token: str, *, secure: bool) -> str:
    cookie = SimpleCookie()
    cookie[AUTH_COOKIE] = auth_token
    session = cookie[AUTH_COOKIE]
    session["httponly"] = True
    session["samesite"] = "Strict"
    session["path"] = "/"
    session["max-age"] = 3600
    if secure:
        session["secure"] = True
    return session.OutputString()


def _theme_input(theme: str) -> str:
    return f'<input type="hidden" name="theme" value="{html.escape(_theme(theme))}">'


def validate_lan_auth_token(provided: str, expected: str) -> None:
    if not _auth_token_valid(provided.strip(), expected):
        raise ValueError("Invalid or missing web GUI auth token.")


def validate_apply_confirmation(form: Mapping[str, list[str]]) -> None:
    if _checked(form, "apply") and _first(form, "confirm_apply").strip() != APPLY_CONFIRMATION:
        raise ValueError(f"Refusing --apply from web GUI without typing {APPLY_CONFIRMATION!r} in the confirmation field.")


def build_web_args(form: Mapping[str, list[str]]) -> list[str]:
    validate_apply_confirmation(form)
    action = _first(form, "action")
    if action == "export":
        return build_export_args(
            _first(form, "provider_from", "discord"),
            source_id=_first(form, "source_id"),
            template=_first(form, "template"),
            out=_first(form, "out", "community.template.json"),
            include_user_overwrites=_checked(form, "include_user_overwrites"),
        )
    if action == "import":
        return build_import_args(
            _values(form, "provider_to", "discord"),
            file=_first(form, "file"),
            target_id=_first(form, "target_id"),
            target_name=_first(form, "target_name"),
            plan_out=_first(form, "plan_out", "-"),
            plan_in=_first(form, "plan_in"),
            journal_out=_first(form, "journal_out"),
            resume_journal=_first(form, "resume_journal"),
            audit_log_reason=_first(form, "audit_log_reason"),
            redact=_checked(form, "redact"),
            apply=_checked(form, "apply"),
            force_invalid_template=_checked(form, "force_invalid_template"),
        )
    if action == "migrate":
        return build_migrate_args(
            _first(form, "provider_from", "discord"),
            _values(form, "provider_to", "fluxer"),
            source_id=_first(form, "source_id"),
            template=_first(form, "template"),
            target_id=_first(form, "target_id"),
            target_name=_first(form, "target_name"),
            template_out=_first(form, "template_out"),
            plan_out=_first(form, "plan_out", "-"),
            plan_in=_first(form, "plan_in"),
            journal_out=_first(form, "journal_out"),
            resume_journal=_first(form, "resume_journal"),
            audit_log_reason=_first(form, "audit_log_reason"),
            include_user_overwrites=_checked(form, "include_user_overwrites"),
            redact=_checked(form, "redact"),
            apply=_checked(form, "apply"),
            force_invalid_template=_checked(form, "force_invalid_template"),
        )
    if action == "content_export":
        return build_content_export_args(
            discord_chat_export=_first(form, "discord_chat_export"),
            source_id=_first(form, "source_id"),
            discord_chat_exporter_bin=_first(form, "discord_chat_exporter_bin"),
            download_discord_chat_exporter=_checked(form, "download_discord_chat_exporter"),
            discord_chat_exporter_version=_first(form, "discord_chat_exporter_version"),
            discord_chat_exporter_install_dir=_first(form, "discord_chat_exporter_install_dir"),
            discord_token_env=_first(form, "discord_token_env"),
            discord_export_out=_first(form, "discord_export_out"),
            discord_export_format=_first(form, "discord_export_format"),
            discord_export_timeout=_first(form, "discord_export_timeout"),
            out=_first(form, "out", "community.content.json"),
        )
    if action == "content_import":
        return build_content_import_args(
            _values(form, "provider_to", "stoat"),
            file=_first(form, "file"),
            target_id=_first(form, "target_id"),
            target_name=_first(form, "target_name"),
            channel_map=_first(form, "channel_map"),
            plan_out=_first(form, "plan_out", "-"),
            plan_in=_first(form, "plan_in"),
            apply=_checked(form, "apply"),
            force_invalid_archive=_checked(form, "force_invalid_archive"),
            message_limit=_first(form, "message_limit"),
            no_authors=_checked(form, "no_authors"),
            no_attachments=_checked(form, "no_attachments"),
            no_reactions=_checked(form, "no_reactions"),
            no_embeds=_checked(form, "no_embeds"),
            no_stickers=_checked(form, "no_stickers"),
            no_polls=_checked(form, "no_polls"),
            no_threads=_checked(form, "no_threads"),
            no_custom_emoji=_checked(form, "no_custom_emoji"),
            native_content=_checked(form, "native_content"),
            ferry_parity=_checked(form, "ferry_parity"),
            download_remote_assets=_checked(form, "download_remote_assets"),
            content_journal_out=_first(form, "content_journal_out"),
            resume_content_journal=_first(form, "resume_content_journal"),
            content_dead_letter_out=_first(form, "content_dead_letter_out"),
            content_report_out=_first(form, "content_report_out"),
            content_lock_file=_first(form, "content_lock_file"),
            content_incremental_state=_first(form, "content_incremental_state"),
            content_incremental=_checked(form, "content_incremental"),
            content_continue_on_error=_checked(form, "content_continue_on_error"),
            content_max_failures=_first(form, "content_max_failures"),
            content_parallel_sends=_first(form, "content_parallel_sends"),
            content_thread_mode=_first(form, "content_thread_mode"),
            content_thread_archive_dir=_first(form, "content_thread_archive_dir"),
        )
    if action == "content_migrate":
        return build_content_migrate_args(
            _values(form, "provider_to", "stoat"),
            discord_chat_export=_first(form, "discord_chat_export"),
            source_id=_first(form, "source_id"),
            discord_chat_exporter_bin=_first(form, "discord_chat_exporter_bin"),
            download_discord_chat_exporter=_checked(form, "download_discord_chat_exporter"),
            discord_chat_exporter_version=_first(form, "discord_chat_exporter_version"),
            discord_chat_exporter_install_dir=_first(form, "discord_chat_exporter_install_dir"),
            discord_token_env=_first(form, "discord_token_env"),
            discord_export_out=_first(form, "discord_export_out"),
            discord_export_format=_first(form, "discord_export_format"),
            discord_export_timeout=_first(form, "discord_export_timeout"),
            target_id=_first(form, "target_id"),
            target_name=_first(form, "target_name"),
            channel_map=_first(form, "channel_map"),
            plan_out=_first(form, "plan_out", "-"),
            plan_in=_first(form, "plan_in"),
            apply=_checked(form, "apply"),
            force_invalid_archive=_checked(form, "force_invalid_archive"),
            message_limit=_first(form, "message_limit"),
            no_authors=_checked(form, "no_authors"),
            no_attachments=_checked(form, "no_attachments"),
            no_reactions=_checked(form, "no_reactions"),
            no_embeds=_checked(form, "no_embeds"),
            no_stickers=_checked(form, "no_stickers"),
            no_polls=_checked(form, "no_polls"),
            no_threads=_checked(form, "no_threads"),
            no_custom_emoji=_checked(form, "no_custom_emoji"),
            native_content=_checked(form, "native_content"),
            ferry_parity=_checked(form, "ferry_parity"),
            download_remote_assets=_checked(form, "download_remote_assets"),
            content_journal_out=_first(form, "content_journal_out"),
            resume_content_journal=_first(form, "resume_content_journal"),
            content_dead_letter_out=_first(form, "content_dead_letter_out"),
            content_report_out=_first(form, "content_report_out"),
            content_lock_file=_first(form, "content_lock_file"),
            content_incremental_state=_first(form, "content_incremental_state"),
            content_incremental=_checked(form, "content_incremental"),
            content_continue_on_error=_checked(form, "content_continue_on_error"),
            content_max_failures=_first(form, "content_max_failures"),
            content_parallel_sends=_first(form, "content_parallel_sends"),
            content_thread_mode=_first(form, "content_thread_mode"),
            content_thread_archive_dir=_first(form, "content_thread_archive_dir"),
        )
    if action == "validate":
        return build_validate_args(_first(form, "file"))
    if action == "redact":
        return build_redact_args(_first(form, "file"), out=_first(form, "out", "redacted.template.json"))
    if action == "platforms":
        return ["platforms", "--check"]
    raise ValueError(f"Unknown web action: {action}")


def _provider_options(selected: str | Sequence[str] = "") -> str:
    selected_values = {selected} if isinstance(selected, str) else set(selected)
    options = []
    for name in sorted(provider_names()):
        mark = " selected" if name in selected_values else ""
        options.append(f'<option value="{html.escape(name)}"{mark}>{html.escape(name)}</option>')
    return "\n".join(options)


def _text_field(
    label: str,
    name: str,
    *,
    value: str = "",
    placeholder: str = "",
    class_name: str = "",
) -> str:
    classes = f"field {class_name}".strip()
    value_attr = f' value="{html.escape(value)}"' if value else ""
    placeholder_attr = f' placeholder="{html.escape(placeholder)}"' if placeholder else ""
    return (
        f'<label class="{classes}"><span>{html.escape(label)}</span>'
        f'<input name="{html.escape(name)}" type="text"{value_attr}{placeholder_attr} '
        'autocomplete="off" autocapitalize="off" spellcheck="false"></label>'
    )


def _select_field(label: str, name: str, options: str) -> str:
    return f'<label class="field"><span>{html.escape(label)}</span><select name="{html.escape(name)}">{options}</select></label>'


def _theme_options(selected: str) -> str:
    selected = _theme(selected)
    return "\n".join(
        f'<option value="{name}"{" selected" if name == selected else ""}>{html.escape(name.title())}</option>'
        for name in THEMES
    )


def _theme_form(theme: str, auth_token: str) -> str:
    return (
        '<form method="get" class="theme-form" aria-label="Theme">'
        f'{_auth_input(auth_token)}'
        '<label class="field field--inline"><span>Theme</span>'
        f'<select name="theme">{_theme_options(theme)}</select></label>'
        '<button type="submit" class="button-secondary">Apply</button>'
        "</form>"
    )


def _multi_select_field(label: str, name: str, options: str) -> str:
    size = min(max(len(provider_names()), 4), 8)
    return (
        f'<label class="field"><span>{html.escape(label)}</span>'
        f'<select name="{html.escape(name)}" multiple size="{size}">{options}</select></label>'
    )


def _checkbox_field(label: str, name: str, *, checked: bool = False, danger: bool = False) -> str:
    checked_attr = " checked" if checked else ""
    danger_class = " check--danger" if danger else ""
    return (
        f'<label class="check{danger_class}">'
        f'<input type="checkbox" name="{html.escape(name)}"{checked_attr}>'
        f"<span>{html.escape(label)}</span></label>"
    )


def _csrf_input(csrf_token: str) -> str:
    return f'<input type="hidden" name="{CSRF_FIELD}" value="{html.escape(csrf_token)}">'


def _apply_confirmation_label() -> str:
    return _text_field(
        "Apply confirmation",
        "confirm_apply",
        placeholder=f"Type {APPLY_CONFIRMATION} after selecting a reviewed plan",
        class_name="field--full field--danger",
    )


def _render_result(result: CommandResult | None) -> str:
    if result is None:
        return ""
    output = result.stdout + result.stderr
    body = html.escape(output or "(no output)")
    preview = html.escape(command_preview(result.args))
    status = "timed out" if result.timed_out else "completed"
    state = "timeout" if result.timed_out else "success" if result.returncode == 0 else "failed"
    title = "Timed out" if result.timed_out else "Succeeded" if result.returncode == 0 else "Failed"
    return f"""
    <section id="result" class="panel output output--{state}" aria-live="polite">
      <div class="panel__header">
        <div>
          <p class="eyebrow">Result</p>
          <h2>{title}</h2>
        </div>
        <span class="status-pill status-pill--{state}">{status}</span>
      </div>
      <p class="command-preview"><code>{preview}</code></p>
      <pre>{body}</pre>
      <dl class="result-meta">
        <div><dt>Exit code</dt><dd>{result.returncode}</dd></div>
        <div><dt>Duration</dt><dd>{result.duration_seconds:.2f}s</dd></div>
      </dl>
    </section>
    """


def render_page(result: CommandResult | None = None, *, csrf_token: str = "", auth_token: str = "", theme: str = "light") -> str:
    theme = _theme(theme)
    checks = runtime_check()
    check_items = "".join(f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>" for key, value in checks.items())
    platforms = "".join(
        "<tr>"
        f"<td>{html.escape(item.name)}</td>"
        f"<td>{html.escape(item.family)}</td>"
        f"<td>{html.escape(item.cli_support)}</td>"
        f"<td>{html.escape(item.desktop_gui_support)}</td>"
        f"<td>{html.escape(item.web_gui_support)}</td>"
        f"<td>{html.escape(item.ci_coverage)}</td>"
        "</tr>"
        for item in SUPPORTED_PLATFORMS
    )
    providers_default = _provider_options("discord")
    providers_fluxer = _provider_options("fluxer")
    thread_mode_options = (
        '<option value="reference" selected>reference</option>'
        '<option value="merge">merge</option>'
        '<option value="channel">channel</option>'
        '<option value="markdown">markdown</option>'
    )
    csrf = _csrf_input(csrf_token)
    auth = _auth_input(auth_token)
    theme_field = _theme_input(theme)
    apply_confirmation = _apply_confirmation_label()
    theme_form = _theme_form(theme, auth_token)
    runtime_badges = "".join(
        f'<span class="badge">{html.escape(label)}: {html.escape(str(checks.get(key, "unknown")))}</span>'
        for label, key in (("CLI", "cli_ready"), ("Desktop", "desktop_gui_ready"), ("Web", "web_gui_ready"))
    )
    return f"""<!doctype html>
<html lang="en" data-theme="{html.escape(theme)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GuildBridge</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f7fa;
      --surface: #ffffff;
      --surface-soft: #f9fafb;
      --border: #d7dee8;
      --border-strong: #aeb8c7;
      --text: #17202a;
      --muted: #586577;
      --header-bg: #101820;
      --header-text: #ffffff;
      --header-muted: #d6dee8;
      --nav-bg: rgba(255, 255, 255, 0.97);
      --hover-bg: #eaf1fb;
      --input-bg: #ffffff;
      --brand: #1f5fbf;
      --brand-strong: #174a96;
      --success: #087443;
      --danger: #b42318;
      --danger-soft: #fff7f5;
      --danger-border: #f3b4ad;
      --warning: #a15c07;
      --code-bg: #111827;
      --code-text: #dce8f5;
    }}
    html[data-theme="dark"] {{
      color-scheme: dark;
      --bg: #10151c;
      --surface: #161d26;
      --surface-soft: #202833;
      --border: #354253;
      --border-strong: #56657a;
      --text: #e7edf5;
      --muted: #a9b6c7;
      --header-bg: #090d12;
      --header-text: #f4f7fb;
      --header-muted: #b5c2d2;
      --nav-bg: rgba(16, 21, 28, 0.97);
      --hover-bg: #223249;
      --input-bg: #0e141b;
      --brand: #6aa4ff;
      --brand-strong: #8bb9ff;
      --success: #2fb176;
      --danger: #ff8f85;
      --danger-soft: #2d1718;
      --danger-border: #7e3838;
      --warning: #e0a64b;
      --code-bg: #070b10;
      --code-text: #e5edf7;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    .skip-link {{
      position: absolute;
      left: 16px;
      top: -48px;
      z-index: 20;
      background: var(--surface);
      color: var(--brand-strong);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px 12px;
    }}
    .skip-link:focus {{ top: 12px; }}
    header {{
      background: var(--header-bg);
      color: var(--header-text);
      border-bottom: 1px solid #253242;
    }}
    .header-inner {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 20px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
    }}
    h1, h2, p {{ margin-top: 0; }}
    h1 {{ margin-bottom: 4px; font-size: 28px; line-height: 1.15; }}
    h2 {{ margin-bottom: 0; font-size: 20px; line-height: 1.2; }}
    header p {{ margin-bottom: 0; color: var(--header-muted); }}
    .badge-row {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 32px;
      padding: 5px 9px;
      border: 1px solid rgba(255, 255, 255, 0.24);
      border-radius: 999px;
      color: #eef4fb;
      background: rgba(255, 255, 255, 0.08);
      white-space: nowrap;
      font-size: 13px;
    }}
    .theme-form {{
      display: flex;
      align-items: end;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .field--inline {{
      min-width: 150px;
    }}
    .tool-nav {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: var(--nav-bg);
      border-bottom: 1px solid var(--border);
    }}
    .tool-nav__inner {{
      max-width: 1180px;
      margin: 0 auto;
      display: flex;
      gap: 8px;
      overflow-x: auto;
      padding: 8px 18px;
      -webkit-overflow-scrolling: touch;
    }}
    .tool-nav a {{
      flex: 0 0 auto;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 8px 12px;
      border-radius: 6px;
      color: var(--text);
      text-decoration: none;
      font-weight: 650;
    }}
    .tool-nav a:focus-visible, .tool-nav a:hover {{ background: var(--hover-bg); outline: none; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 18px; }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 16px;
      scroll-margin-top: 72px;
    }}
    .panel__header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    .eyebrow {{
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
      text-transform: uppercase;
    }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(220px, 1fr));
      gap: 12px 14px;
      align-items: end;
    }}
    .field {{ display: grid; gap: 6px; font-size: 14px; font-weight: 650; }}
    .field--full {{ grid-column: 1 / -1; }}
    .field--danger span {{ color: var(--danger); }}
    input, select, button {{ font: inherit; }}
    input, select {{
      width: 100%;
      min-height: 44px;
      border: 1px solid var(--border-strong);
      border-radius: 6px;
      padding: 9px 10px;
      background: var(--input-bg);
      color: var(--text);
    }}
    select[multiple] {{ min-height: 168px; padding: 6px; }}
    select[multiple] option {{ padding: 6px 8px; }}
    input:focus-visible, select:focus-visible, button:focus-visible {{
      outline: 3px solid #9cc2ff;
      outline-offset: 2px;
    }}
    .check {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 44px;
      padding: 9px 10px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: var(--surface-soft);
      font-weight: 650;
    }}
    .check input {{ width: 18px; min-height: 18px; }}
    .check--danger {{ border-color: var(--danger-border); background: var(--danger-soft); color: var(--danger); }}
    .form-actions {{
      grid-column: 1 / -1;
      display: flex;
      justify-content: flex-end;
      gap: 10px;
    }}
    button {{
      min-height: 44px;
      border: 0;
      border-radius: 6px;
      padding: 9px 16px;
      background: var(--brand);
      color: #ffffff;
      font-weight: 750;
      cursor: pointer;
    }}
    .button-secondary {{
      background: var(--surface-soft);
      color: var(--text);
      border: 1px solid var(--border-strong);
    }}
    .button-secondary:hover {{ background: var(--hover-bg); }}
    button:hover {{ background: var(--brand-strong); }}
    .tool-stack {{ display: grid; gap: 14px; }}
    pre {{
      max-height: 420px;
      overflow: auto;
      background: var(--code-bg);
      color: var(--code-text);
      padding: 12px;
      border-radius: 6px;
    }}
    .command-preview {{ overflow-wrap: anywhere; margin-bottom: 10px; }}
    .status-pill {{
      flex: 0 0 auto;
      border-radius: 999px;
      padding: 5px 10px;
      color: #ffffff;
      font-size: 13px;
      font-weight: 750;
      text-transform: capitalize;
    }}
    .status-pill--success {{ background: var(--success); }}
    .status-pill--failed {{ background: var(--danger); }}
    .status-pill--timeout {{ background: var(--warning); }}
    .output--success {{ border-left: 4px solid var(--success); }}
    .output--failed {{ border-left: 4px solid var(--danger); }}
    .output--timeout {{ border-left: 4px solid var(--warning); }}
    .result-meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 8px;
      margin: 10px 0 0;
    }}
    .result-meta div {{ border: 1px solid var(--border); border-radius: 6px; padding: 8px; background: var(--surface-soft); }}
    .result-meta dt {{ color: var(--muted); font-size: 12px; font-weight: 750; text-transform: uppercase; }}
    .result-meta dd {{ margin: 2px 0 0; font-weight: 750; }}
    .runtime-list {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 8px;
      padding: 0;
      margin: 0 0 14px;
      list-style: none;
    }}
    .runtime-list li {{ border: 1px solid var(--border); border-radius: 6px; padding: 8px 10px; background: var(--surface-soft); overflow-wrap: anywhere; }}
    .table-wrap {{ overflow-x: auto; border: 1px solid var(--border); border-radius: 8px; }}
    table {{ border-collapse: collapse; width: 100%; min-width: 840px; background: var(--surface); }}
    th, td {{ border-bottom: 1px solid var(--border); padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ background: var(--surface-soft); font-size: 13px; color: var(--muted); }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    @media (max-width: 720px) {{
      .header-inner {{ display: grid; padding: 18px 14px; }}
      .theme-form {{ justify-content: flex-start; }}
      .badge-row {{ justify-content: flex-start; }}
      main {{ padding: 14px 12px; }}
      .tool-nav__inner {{ padding-inline: 12px; }}
      .panel {{ border-radius: 0; border-left: 0; border-right: 0; margin-left: -12px; margin-right: -12px; padding: 14px 12px; }}
      .panel__header {{ display: grid; }}
      .form-grid {{ grid-template-columns: 1fr; }}
      .form-actions {{ justify-content: stretch; }}
      .form-actions button, button {{ width: 100%; }}
      .runtime-list {{ grid-template-columns: 1fr; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      html {{ scroll-behavior: auto; }}
    }}
  </style>
</head>
<body>
  <a class="skip-link" href="#migrate">Skip to migrate</a>
  <header>
    <div class="header-inner">
      <div>
        <h1>GuildBridge</h1>
        <p>Community migration workspace</p>
      </div>
      <div>
        <div class="badge-row" aria-label="Runtime readiness">{runtime_badges}</div>
        {theme_form}
      </div>
    </div>
  </header>
  <nav class="tool-nav" aria-label="GuildBridge tools">
    <div class="tool-nav__inner">
      <a href="#migrate">Migrate</a>
      <a href="#export">Export</a>
      <a href="#import">Import</a>
      <a href="#content-migration">Content</a>
      <a href="#tools">Validate</a>
      <a href="#runtime">Runtime</a>
      <a href="#platforms">Platforms</a>
    </div>
  </nav>
  <main id="content">
    {_render_result(result)}

    <section id="migrate" class="panel">
      <div class="panel__header"><h2>Migrate</h2></div>
      <form method="post" action="/run" class="form-grid" aria-label="Migrate community">
        {csrf}
        {auth}
        {theme_field}
        <input type="hidden" name="action" value="migrate">
        {_select_field("From", "provider_from", providers_default)}
        {_multi_select_field("To", "provider_to", providers_fluxer)}
        {_text_field("Source ID", "source_id")}
        {_text_field("Template URL/code", "template")}
        {_text_field("Target ID", "target_id")}
        {_text_field("Target name", "target_name")}
        {_text_field("Template output", "template_out")}
        {_text_field("Plan/result output", "plan_out", value="-")}
        {_text_field("Reviewed plan input", "plan_in")}
        {_text_field("Journal output", "journal_out")}
        {_text_field("Resume journal", "resume_journal")}
        {_text_field("Audit reason", "audit_log_reason")}
        {_checkbox_field("Redact before import", "redact", checked=True)}
        {_checkbox_field("Include user overwrites", "include_user_overwrites")}
        {_checkbox_field("Force invalid template after review", "force_invalid_template", danger=True)}
        {_checkbox_field("Apply writes", "apply", danger=True)}
        {apply_confirmation}
        <div class="form-actions"><button type="submit">Run Migrate</button></div>
      </form>
    </section>

    <section id="export" class="panel">
      <div class="panel__header"><h2>Export</h2></div>
      <form method="post" action="/run" class="form-grid" aria-label="Export community">
        {csrf}
        {auth}
        {theme_field}
        <input type="hidden" name="action" value="export">
        {_select_field("From", "provider_from", providers_default)}
        {_text_field("Source ID", "source_id")}
        {_text_field("Template URL/code", "template")}
        {_text_field("Output", "out", value="community.template.json")}
        {_checkbox_field("Include user overwrites", "include_user_overwrites")}
        <div class="form-actions"><button type="submit">Run Export</button></div>
      </form>
    </section>

    <section id="import" class="panel">
      <div class="panel__header"><h2>Import</h2></div>
      <form method="post" action="/run" class="form-grid" aria-label="Import community">
        {csrf}
        {auth}
        {theme_field}
        <input type="hidden" name="action" value="import">
        {_multi_select_field("To", "provider_to", providers_default)}
        {_text_field("Template file", "file")}
        {_text_field("Target ID", "target_id")}
        {_text_field("Target name", "target_name")}
        {_text_field("Plan/result output", "plan_out", value="-")}
        {_text_field("Reviewed plan input", "plan_in")}
        {_text_field("Journal output", "journal_out")}
        {_text_field("Resume journal", "resume_journal")}
        {_text_field("Audit reason", "audit_log_reason")}
        {_checkbox_field("Redact before import", "redact")}
        {_checkbox_field("Force invalid template after review", "force_invalid_template", danger=True)}
        {_checkbox_field("Apply writes", "apply", danger=True)}
        {apply_confirmation}
        <div class="form-actions"><button type="submit">Run Import</button></div>
      </form>
    </section>

    <section id="content-migration" class="panel">
      <div class="panel__header"><h2>Content</h2></div>
      <div class="tool-stack">
        <form method="post" action="/run" class="form-grid" aria-label="Export content archive">
          {csrf}
          {auth}
          {theme_field}
          <input type="hidden" name="action" value="content_export">
          {_text_field("DiscordChatExporter file/folder", "discord_chat_export")}
          {_text_field("Discord guild/server ID", "source_id")}
          {_text_field("DiscordChatExporter app", "discord_chat_exporter_bin")}
          {_checkbox_field("Download DiscordChatExporter if needed", "download_discord_chat_exporter")}
          {_text_field("Managed DCE version", "discord_chat_exporter_version", value="latest")}
          {_text_field("Managed DCE install folder", "discord_chat_exporter_install_dir")}
          {_text_field("Discord token env var", "discord_token_env", value="DISCORD_TOKEN")}
          {_text_field("Discord export output", "discord_export_out")}
          {_text_field("Discord export format", "discord_export_format", value="Json")}
          {_text_field("Discord export timeout", "discord_export_timeout", value="3600")}
          {_text_field("Archive output", "out", value="community.content.json")}
          <div class="form-actions"><button type="submit">Export Content Archive</button></div>
        </form>
        <form method="post" action="/run" class="form-grid" aria-label="Migrate content">
          {csrf}
          {auth}
          {theme_field}
          <input type="hidden" name="action" value="content_migrate">
          {_text_field("DiscordChatExporter file/folder", "discord_chat_export")}
          {_text_field("Discord guild/server ID", "source_id")}
          {_text_field("DiscordChatExporter app", "discord_chat_exporter_bin")}
          {_checkbox_field("Download DiscordChatExporter if needed", "download_discord_chat_exporter")}
          {_text_field("Managed DCE version", "discord_chat_exporter_version", value="latest")}
          {_text_field("Managed DCE install folder", "discord_chat_exporter_install_dir")}
          {_text_field("Discord token env var", "discord_token_env", value="DISCORD_TOKEN")}
          {_text_field("Discord export output", "discord_export_out")}
          {_text_field("Discord export format", "discord_export_format", value="Json")}
          {_text_field("Discord export timeout", "discord_export_timeout", value="3600")}
          {_multi_select_field("To", "provider_to", providers_fluxer)}
          {_text_field("Target ID", "target_id")}
          {_text_field("Target name", "target_name")}
          {_text_field("Channel map JSON", "channel_map")}
          {_text_field("Plan/result output", "plan_out", value="-")}
          {_text_field("Reviewed plan input", "plan_in")}
          {_text_field("Content journal output", "content_journal_out")}
          {_text_field("Resume content journal", "resume_content_journal")}
          {_text_field("Dead-letter output", "content_dead_letter_out")}
          {_text_field("Report output", "content_report_out")}
          {_text_field("Content lock file", "content_lock_file")}
          {_text_field("Incremental state", "content_incremental_state")}
          {_text_field("Message limit", "message_limit")}
          {_text_field("Max failures", "content_max_failures", value="1")}
          {_text_field("Parallel sends", "content_parallel_sends", value="1")}
          {_select_field("Thread mode", "content_thread_mode", thread_mode_options)}
          {_text_field("Thread archive folder", "content_thread_archive_dir")}
          {_checkbox_field("Omit author names", "no_authors")}
          {_checkbox_field("Omit attachment references", "no_attachments")}
          {_checkbox_field("Omit reactions", "no_reactions")}
          {_checkbox_field("Omit embeds", "no_embeds")}
          {_checkbox_field("Omit stickers", "no_stickers")}
          {_checkbox_field("Omit polls", "no_polls")}
          {_checkbox_field("Omit thread/forum references", "no_threads")}
          {_checkbox_field("Omit custom emoji summary", "no_custom_emoji")}
          {_checkbox_field("Use provider-native content features", "native_content")}
          {_checkbox_field("Discord -> Stoat full-fidelity preset", "ferry_parity")}
          {_checkbox_field("Download remote media/assets", "download_remote_assets")}
          {_checkbox_field("Use incremental state", "content_incremental")}
          {_checkbox_field("Continue after failed messages", "content_continue_on_error")}
          {_checkbox_field("Force invalid archive after review", "force_invalid_archive", danger=True)}
          {_checkbox_field("Apply writes", "apply", danger=True)}
          {apply_confirmation}
          <div class="form-actions"><button type="submit">Run Content Migrate</button></div>
        </form>
        <form method="post" action="/run" class="form-grid" aria-label="Import content archive">
          {csrf}
          {auth}
          {theme_field}
          <input type="hidden" name="action" value="content_import">
          {_text_field("Content archive file", "file")}
          {_multi_select_field("To", "provider_to", providers_default)}
          {_text_field("Target ID", "target_id")}
          {_text_field("Target name", "target_name")}
          {_text_field("Channel map JSON", "channel_map")}
          {_text_field("Plan/result output", "plan_out", value="-")}
          {_text_field("Reviewed plan input", "plan_in")}
          {_text_field("Content journal output", "content_journal_out")}
          {_text_field("Resume content journal", "resume_content_journal")}
          {_text_field("Dead-letter output", "content_dead_letter_out")}
          {_text_field("Report output", "content_report_out")}
          {_text_field("Content lock file", "content_lock_file")}
          {_text_field("Incremental state", "content_incremental_state")}
          {_text_field("Message limit", "message_limit")}
          {_text_field("Max failures", "content_max_failures", value="1")}
          {_text_field("Parallel sends", "content_parallel_sends", value="1")}
          {_select_field("Thread mode", "content_thread_mode", thread_mode_options)}
          {_text_field("Thread archive folder", "content_thread_archive_dir")}
          {_checkbox_field("Omit author names", "no_authors")}
          {_checkbox_field("Omit attachment references", "no_attachments")}
          {_checkbox_field("Omit reactions", "no_reactions")}
          {_checkbox_field("Omit embeds", "no_embeds")}
          {_checkbox_field("Omit stickers", "no_stickers")}
          {_checkbox_field("Omit polls", "no_polls")}
          {_checkbox_field("Omit thread/forum references", "no_threads")}
          {_checkbox_field("Omit custom emoji summary", "no_custom_emoji")}
          {_checkbox_field("Use provider-native content features", "native_content")}
          {_checkbox_field("Discord -> Stoat full-fidelity preset", "ferry_parity")}
          {_checkbox_field("Download remote media/assets", "download_remote_assets")}
          {_checkbox_field("Use incremental state", "content_incremental")}
          {_checkbox_field("Continue after failed messages", "content_continue_on_error")}
          {_checkbox_field("Force invalid archive after review", "force_invalid_archive", danger=True)}
          {_checkbox_field("Apply writes", "apply", danger=True)}
          {apply_confirmation}
          <div class="form-actions"><button type="submit">Run Content Import</button></div>
        </form>
      </div>
    </section>

    <section id="tools" class="panel">
      <div class="panel__header"><h2>Validate / Redact</h2></div>
      <div class="tool-stack">
        <form method="post" action="/run" class="form-grid" aria-label="Validate template">
          {csrf}
          {auth}
          {theme_field}
          <input type="hidden" name="action" value="validate">
          {_text_field("Template file", "file")}
          <div class="form-actions"><button type="submit">Validate</button></div>
        </form>
        <form method="post" action="/run" class="form-grid" aria-label="Redact template">
          {csrf}
          {auth}
          {theme_field}
          <input type="hidden" name="action" value="redact">
          {_text_field("Template file", "file")}
          {_text_field("Output", "out", value="redacted.template.json")}
          <div class="form-actions"><button type="submit">Redact</button></div>
        </form>
      </div>
    </section>

    <section id="runtime" class="panel">
      <div class="panel__header"><h2>Runtime</h2></div>
      <ul class="runtime-list">{check_items}</ul>
      <form method="post" action="/run">
        {csrf}
        {auth}
        {theme_field}
        <input type="hidden" name="action" value="platforms">
        <button type="submit">Run Platform Check</button>
      </form>
    </section>

    <section id="platforms" class="panel">
      <div class="panel__header"><h2>Supported Platforms</h2></div>
      <div class="table-wrap" role="region" aria-label="Supported platform matrix" tabindex="0">
        <table><thead><tr><th>Platform</th><th>Family</th><th>CLI</th><th>Desktop GUI</th><th>Web GUI</th><th>CI</th></tr></thead><tbody>{platforms}</tbody></table>
      </div>
    </section>
  </main>
</body>
</html>
"""


class GuildBridgeWebHandler(BaseHTTPRequestHandler):
    csrf_token = ""
    auth_token = ""
    require_auth = False
    allow_lan = False
    secure_cookies = False
    max_body_bytes = DEFAULT_MAX_BODY_BYTES

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query_form = parse_qs(parsed.query, keep_blank_values=True)
        if self.require_auth and not self._request_auth_ok():
            if _auth_token_valid(_first(query_form, AUTH_FIELD).strip(), self.auth_token):
                self._start_authenticated_session(_theme(_first(query_form, "theme", "light")))
                return
            self.send_error(HTTPStatus.UNAUTHORIZED, "Invalid or missing auth token")
            return
        theme = _theme(_first(query_form, "theme", "light"))
        self._send_html(render_page(csrf_token=self.csrf_token, theme=theme))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not self.allow_lan and not _is_loopback_address(str(self.client_address[0])):
            self.send_error(HTTPStatus.FORBIDDEN, "LAN clients require --allow-lan")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length")
            return
        if length > self.max_body_bytes:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body is too large")
            return
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw, keep_blank_values=True)
        if self.require_auth:
            if not self._request_auth_ok():
                self.send_error(HTTPStatus.UNAUTHORIZED, "Invalid or missing auth token")
                return
        if _first(form, CSRF_FIELD) != self.csrf_token:
            self.send_error(HTTPStatus.FORBIDDEN, "Invalid CSRF token")
            return
        try:
            args = build_web_args(form)
            result = run_cli_args(args)
        except Exception as exc:  # noqa: BLE001 - request boundary returns a sanitized error page instead of dropping the session.
            result = CommandResult((), (), 1, "", format_error_report(exc), 0.0)
        self._send_html(
            render_page(
                result,
                csrf_token=self.csrf_token,
                theme=_first(form, "theme", "light"),
            )
        )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self) -> None:
        self._send_security_headers()
        super().end_headers()

    def _send_security_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")

    def _request_auth_ok(self) -> bool:
        provided = self.headers.get(AUTH_HEADER, "").strip()
        if _auth_token_valid(provided, self.auth_token):
            return True
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
            cookie = cookies.get(AUTH_COOKIE)
        except (CookieError, ValueError):
            return False
        return cookie is not None and _auth_token_valid(cookie.value, self.auth_token)

    def _start_authenticated_session(self, theme: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", f"/?theme={_theme(theme)}")
        self.send_header("Set-Cookie", _session_cookie(self.auth_token, secure=self.secure_cookies))
        self.end_headers()


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    allow_lan: bool = False,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    auth_token: str | None = None,
    tls_cert: str | None = None,
    tls_key: str | None = None,
) -> None:
    if max_body_bytes < 1024:
        raise ValueError("max_body_bytes must be at least 1024")
    if not allow_lan and not _is_loopback_host(host):
        raise ValueError("Refusing to bind web GUI to a non-loopback host without --allow-lan.")
    if bool(tls_cert) != bool(tls_key):
        raise ValueError("--tls-cert and --tls-key must be supplied together.")
    if allow_lan and not (tls_cert and tls_key):
        raise ValueError("LAN web GUI requires --tls-cert and --tls-key to protect migration credentials in transit.")
    require_auth = allow_lan
    token = (auth_token or "").strip()
    if require_auth and not token:
        raise ValueError("LAN web GUI requires --auth-token or GUILDBRIDGE_WEB_AUTH_TOKEN.")
    GuildBridgeWebHandler.csrf_token = secrets.token_urlsafe(32)
    GuildBridgeWebHandler.auth_token = token
    GuildBridgeWebHandler.require_auth = require_auth
    GuildBridgeWebHandler.allow_lan = allow_lan
    GuildBridgeWebHandler.secure_cookies = bool(tls_cert)
    GuildBridgeWebHandler.max_body_bytes = max_body_bytes
    server = ThreadingHTTPServer((host, port), GuildBridgeWebHandler)
    if tls_cert and tls_key:
        context = _create_tls_server_context()
        context.load_cert_chain(tls_cert, tls_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    scope = "LAN-enabled" if allow_lan else "local-only"
    scheme = "https" if tls_cert else "http"
    print(f"GuildBridge web GUI ({scope}): {scheme}://{host}:{port}")
    if require_auth:
        print(f"LAN auth is enabled. Open {scheme}://{host}:{port}/?{AUTH_FIELD}=<token> once to start a secure session.")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the GuildBridge browser-based GUI.")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host", default="127.0.0.1", help="host/interface to bind")
    parser.add_argument("--port", type=int, default=8765, help="port to bind")
    parser.add_argument("--allow-lan", action="store_true", help="allow binding to non-loopback interfaces and serving LAN clients")
    parser.add_argument("--max-body-bytes", type=int, default=DEFAULT_MAX_BODY_BYTES, help="maximum accepted POST body size")
    parser.add_argument("--auth-token", default=os.environ.get("GUILDBRIDGE_WEB_AUTH_TOKEN"), help="LAN auth token; may be supplied through GUILDBRIDGE_WEB_AUTH_TOKEN")
    parser.add_argument("--tls-cert", help="PEM certificate required for --allow-lan")
    parser.add_argument("--tls-key", help="PEM private key required for --allow-lan")
    args = parser.parse_args(argv)
    serve(args.host, args.port, allow_lan=args.allow_lan, max_body_bytes=args.max_body_bytes, auth_token=args.auth_token, tls_cert=args.tls_cert, tls_key=args.tls_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

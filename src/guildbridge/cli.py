from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from guildbridge.access import check_provider_access
from guildbridge.config import RuntimeConfig
from guildbridge.content import (
    CONTENT_FEATURES,
    ContentArchive,
    ContentImportOptions,
    DiscordChatExporterBootstrapOptions,
    DiscordChatExporterOptions,
    ThreadMode,
    content_archive_fingerprint,
    content_capabilities_document,
    content_capabilities_table,
    content_not_implemented_message,
    download_discord_chat_exporter,
    load_channel_map,
    load_content_archive,
    load_discord_chat_export,
    run_discord_chat_exporter,
    selected_content_features,
)
from guildbridge.diagnostics import format_error_report
from guildbridge.journal import (
    ApplyJournal,
    ApplyJournalContext,
    default_journal_path,
    template_fingerprint,
    utc_now,
    validate_resume_journal,
)
from guildbridge.models import CommunityTemplate, ImportResult
from guildbridge.plan import (
    PLAN_SCHEMA,
    action_fingerprint,
    apply_result_plan_metadata,
    build_plan_context,
    build_plan_metadata,
    result_to_dict,
    validate_reviewed_plan,
    validate_reviewed_plan_data,
)
from guildbridge.platforms import CHECK_TARGETS, SUPPORTED_PLATFORMS, evaluate_runtime_check, runtime_check
from guildbridge.privacy import redact_template
from guildbridge.providers import get_provider, provider_names
from guildbridge.providers.base import ExportOptions, ImportOptions, Provider
from guildbridge.routes import structure_route_document, structure_routes_table
from guildbridge.safety import APPLY_CONFIRMATION, validate_apply_safety

BATCH_RESULT_SCHEMA = "guildbridge.batch-result.v1"


@dataclass(frozen=True)
class TargetSpec:
    requested_name: str
    provider: Provider
    target_id: str | None
    target_name: str | None


def _safe_cli_path_part(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-") or "target"


def _ferry_artifact_path(target: TargetSpec, filename: str) -> str:
    target_part = _safe_cli_path_part(target.target_id or target.target_name or target.provider.name)
    return str(Path(".guildbridge") / "content" / "ferry-parity" / target.provider.name / target_part / filename)


def load_template(path: str | Path) -> CommunityTemplate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CommunityTemplate.from_dict(data)


def write_json(data: dict[str, Any], path: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if not path or path == "-":
        write_stdout_utf8(text)
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def write_stdout_utf8(text: str) -> None:
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def configure_stdio_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # Some redirected or embedded consoles do not support reconfigure().
            continue


def prepare_apply_journal(
    args: argparse.Namespace,
    *,
    command: str,
    provider: str,
    template: CommunityTemplate,
    source_provider: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
    reviewed_plan_hash: str | None = None,
    journal_out: str | None = None,
    resume_journal: str | None = None,
) -> ApplyJournal | None:
    if journal_out is None:
        journal_out = getattr(args, "journal_out", None)
    if resume_journal is None:
        resume_journal = getattr(args, "resume_journal", None)
    if resume_journal and not args.apply:
        raise ValueError("--resume-journal requires --apply.")
    if journal_out == "-":
        raise ValueError("--journal-out must be a file path, not '-'.")
    if not args.apply and not journal_out:
        return None

    context = ApplyJournalContext(
        command=command,
        provider=provider,
        source_provider=source_provider,
        template_hash=template_fingerprint(template),
        template_name=template.name,
        target_id=target_id,
        target_name=target_name,
        reviewed_plan_hash=reviewed_plan_hash,
        plan_out=getattr(args, "plan_out", None),
    )
    if resume_journal:
        validate_resume_journal(resume_journal, context)

    path = Path(journal_out) if journal_out else default_journal_path(command, provider)
    journal = ApplyJournal(path, context, resumed_from=resume_journal)
    journal.start()
    print(f"Apply journal: {journal.path}", file=sys.stderr)
    return journal


def validate_apply_plan_args(args: argparse.Namespace) -> None:
    plan_in = getattr(args, "plan_in", None)
    if plan_in and not args.apply:
        raise ValueError("--plan-in is only used with --apply.")
    if args.apply and not plan_in:
        raise ValueError(
            "Refusing --apply without --plan-in <reviewed dry-run plan>. "
            "Run without --apply first, review the plan, then rerun with --plan-in."
        )


def _split_cli_values(values: str | Sequence[str] | None, *, split_commas: bool) -> list[str]:
    if values is None:
        return []
    raw_values = [values] if isinstance(values, str) else list(values)
    normalized: list[str] = []
    for raw_value in raw_values:
        parts = raw_value.split(",") if split_commas else [raw_value]
        normalized.extend(part.strip() for part in parts if part.strip())
    return normalized


def _provider_targets(values: str | Sequence[str] | None) -> list[str]:
    targets = _split_cli_values(values, split_commas=True)
    if not targets:
        raise ValueError("At least one --to provider is required.")
    return targets


def _selected_content_features_from_args(args: argparse.Namespace) -> list[str]:
    return selected_content_features(
        include_content=bool(getattr(args, "include_content", False)),
        requested_features=list(getattr(args, "content_feature", None) or []),
    )


def _reject_unsupported_content(
    args: argparse.Namespace,
    *,
    source_provider: str | None,
    target_providers: list[str],
) -> None:
    features = _selected_content_features_from_args(args)
    if not features:
        return
    raise ValueError(
        content_not_implemented_message(
            source_provider=source_provider,
            target_providers=target_providers,
            features=features,
        )
    )


def _provider_option_value(
    values: str | Sequence[str] | None,
    *,
    provider_name: str,
    requested_name: str,
    option: str,
) -> str | None:
    raw_values = _split_cli_values(values, split_commas=False)
    mapped: dict[str, str] = {}
    defaults: list[str] = []
    for raw_value in raw_values:
        if "=" in raw_value:
            key, value = raw_value.split("=", 1)
            key = key.strip().lower()
            if not key:
                raise ValueError(f"{option} provider mapping is missing a provider name.")
            mapped[key] = value.strip()
        else:
            defaults.append(raw_value)
    for key in (provider_name.lower(), requested_name.lower()):
        if key in mapped:
            return mapped[key] or None
    if len(defaults) > 1:
        raise ValueError(f"{option} accepts only one global value. Use provider=value for provider-specific values.")
    return defaults[0] if defaults else None


def _target_specs(args: argparse.Namespace, config: RuntimeConfig) -> list[TargetSpec]:
    targets: list[TargetSpec] = []
    seen: set[str] = set()
    for requested_name in _provider_targets(args.provider_to):
        provider = get_provider(requested_name, config)
        if provider.name in seen:
            raise ValueError(f"Duplicate target provider after alias resolution: {provider.name}.")
        seen.add(provider.name)
        targets.append(
            TargetSpec(
                requested_name=requested_name,
                provider=provider,
                target_id=_provider_option_value(
                    getattr(args, "target_id", None),
                    provider_name=provider.name,
                    requested_name=requested_name,
                    option="--target-id",
                ),
                target_name=_provider_option_value(
                    getattr(args, "target_name", None),
                    provider_name=provider.name,
                    requested_name=requested_name,
                    option="--target-name",
                ),
            )
        )
    return targets


def _provider_path(
    values: str | Sequence[str] | None,
    *,
    provider_name: str,
    requested_name: str,
    option: str,
    multi_target: bool,
) -> str | None:
    value = _provider_option_value(values, provider_name=provider_name, requested_name=requested_name, option=option)
    if not value or not multi_target:
        return value
    path = Path(value)
    suffix = path.suffix
    name = f"{path.stem}.{provider_name}{suffix}" if suffix else f"{path.name}.{provider_name}"
    return str(path.with_name(name))


def _load_reviewed_batch_plan(
    path: str | Path,
    *,
    command: str,
    source_provider: str | None,
    target_providers: Sequence[str],
) -> dict[str, dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != BATCH_RESULT_SCHEMA:
        raise ValueError(f"Reviewed batch plan has unsupported schema: {data.get('schema')!r}")
    if data.get("applied") is not False:
        raise ValueError("Reviewed batch plan must be a dry-run result with applied=false.")
    if data.get("command") != command:
        raise ValueError(f"Reviewed batch plan has different command: {data.get('command')!r} != {command!r}.")
    if data.get("source_provider") != source_provider:
        raise ValueError(
            f"Reviewed batch plan has different source_provider: {data.get('source_provider')!r} != {source_provider!r}."
        )
    reviewed_targets = data.get("target_providers")
    if sorted(reviewed_targets or []) != sorted(target_providers):
        raise ValueError(
            f"Reviewed batch plan has different target providers: {reviewed_targets!r} != {list(target_providers)!r}."
        )
    results = data.get("results")
    if not isinstance(results, list):
        raise ValueError("Reviewed batch plan is missing a results list.")
    by_provider: dict[str, dict[str, Any]] = {}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Reviewed batch plan contains a non-object result.")
        provider = result.get("provider")
        if not isinstance(provider, str) or not provider:
            raise ValueError("Reviewed batch plan result is missing a provider.")
        if provider in by_provider:
            raise ValueError(f"Reviewed batch plan contains duplicate provider result: {provider}.")
        if result.get("applied") is not False:
            raise ValueError(f"Reviewed batch plan result for {provider} must have applied=false.")
        by_provider[provider] = result
    missing = [provider for provider in target_providers if provider not in by_provider]
    if missing:
        raise ValueError(f"Reviewed batch plan is missing target provider result(s): {', '.join(missing)}.")
    return by_provider


def _batch_result(
    *,
    command: str,
    target_providers: Sequence[str],
    results: list[dict[str, Any]],
    source_provider: str | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": BATCH_RESULT_SCHEMA,
        "command": command,
        "applied": all(result.get("applied") is True for result in results),
        "target_providers": list(target_providers),
        "target_count": len(target_providers),
        "action_count": sum(len(result.get("actions", [])) for result in results),
        "results": results,
    }
    if source_provider is not None:
        data["source_provider"] = source_provider
    return data


def _content_plan_metadata(
    *,
    command: str,
    provider: str,
    archive_name: str,
    archive_hash: str,
    result: ImportResult,
    source_provider: str | None = None,
    target_id: str | None = None,
    target_name: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": PLAN_SCHEMA,
        "created_at": utc_now(),
        "context": {
            "command": command,
            "provider": provider,
            "source_provider": source_provider,
            "template_hash": archive_hash,
            "template_name": archive_name,
            "target_id": target_id,
            "target_name": target_name,
        },
        "action_count": len(result.actions),
        "action_hash": action_fingerprint(result.actions),
    }


def _import_to_target(
    args: argparse.Namespace,
    *,
    template: CommunityTemplate,
    target: TargetSpec,
    command: str,
    source_provider: str | None = None,
    reviewed_data: dict[str, Any] | None = None,
    multi_target: bool = False,
) -> dict[str, Any]:
    plan_context = build_plan_context(
        command=command,
        provider=target.provider.name,
        source_provider=source_provider,
        template=template,
        target_id=target.target_id,
        target_name=target.target_name,
    )
    reviewed_plan_hash: str | None = None
    output_plan: dict[str, Any] | None = None
    if args.apply:
        candidate = target.provider.import_template(
            template,
            ImportOptions(
                target_id=target.target_id,
                target_name=target.target_name,
                apply=False,
                audit_log_reason=args.audit_log_reason,
            ),
        )
        candidate_plan = build_plan_metadata(plan_context, candidate)
        if reviewed_data is None:
            reviewed_plan = validate_reviewed_plan(args.plan_in, candidate_plan)
        else:
            reviewed_plan = validate_reviewed_plan_data(reviewed_data, candidate_plan)
        reviewed_plan_hash = str(reviewed_plan["action_hash"])
        output_plan = apply_result_plan_metadata(candidate_plan, args.plan_in)
    journal = prepare_apply_journal(
        args,
        command=command,
        provider=target.provider.name,
        source_provider=source_provider,
        template=template,
        target_id=target.target_id,
        target_name=target.target_name,
        reviewed_plan_hash=reviewed_plan_hash,
        journal_out=_provider_path(
            getattr(args, "journal_out", None),
            provider_name=target.provider.name,
            requested_name=target.requested_name,
            option="--journal-out",
            multi_target=multi_target,
        ),
        resume_journal=_provider_path(
            getattr(args, "resume_journal", None),
            provider_name=target.provider.name,
            requested_name=target.requested_name,
            option="--resume-journal",
            multi_target=multi_target,
        ),
    )
    try:
        result = target.provider.import_template(
            template,
            ImportOptions(
                target_id=target.target_id,
                target_name=target.target_name,
                apply=args.apply,
                audit_log_reason=args.audit_log_reason,
                journal=journal,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary converts unexpected command failures into sanitized diagnostics.
        if journal:
            journal.fail(exc)
        raise
    if output_plan is None:
        output_plan = build_plan_metadata(plan_context, result)
    if journal:
        journal.finish(result)
    return result_to_dict(result, plan=output_plan)


def command_export(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    provider = get_provider(args.provider_from, config)
    _reject_unsupported_content(args, source_provider=provider.name, target_providers=[])
    template = provider.export_template(
        ExportOptions(source_id=args.source_id, template=args.template, include_user_overwrites=args.include_user_overwrites)
    )
    problems = template.validate()
    if problems:
        template.warnings.extend(problems)
    write_json(template.to_dict(), args.out)
    print(f"Exported {len(template.roles)} roles, {len(template.categories)} categories, {len(template.channels)} channels.", file=sys.stderr)
    return 0


def command_import(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    targets = _target_specs(args, config)
    _reject_unsupported_content(args, source_provider=None, target_providers=[target.provider.name for target in targets])
    template = load_template(args.file)
    if args.redact:
        template = redact_template(template)
    problems = template.validate()
    if problems:
        print("Template validation problems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
    validate_apply_safety(
        apply=args.apply,
        confirm_apply=args.confirm_apply,
        validation_problems=problems,
        force_invalid_template=args.force_invalid_template,
    )
    validate_apply_plan_args(args)
    multi_target = len(targets) > 1
    reviewed_batch = (
        _load_reviewed_batch_plan(
            args.plan_in,
            command="import",
            source_provider=None,
            target_providers=[target.provider.name for target in targets],
        )
        if args.apply and multi_target
        else None
    )
    results = [
        _import_to_target(
            args,
            template=template,
            target=target,
            command="import",
            reviewed_data=reviewed_batch.get(target.provider.name) if reviewed_batch else None,
            multi_target=multi_target,
        )
        for target in targets
    ]
    if multi_target:
        write_json(
            _batch_result(command="import", target_providers=[target.provider.name for target in targets], results=results),
            args.plan_out,
        )
        action_count = sum(len(result.get("actions", [])) for result in results)
        if args.apply:
            print(f"Applied {action_count} actions across {len(targets)} targets.", file=sys.stderr)
        else:
            print(
                f"Planned {action_count} actions across {len(targets)} targets. "
                f"Use --apply --confirm-apply {APPLY_CONFIRMATION} --plan-in <reviewed-batch-plan.json> to execute writes.",
                file=sys.stderr,
            )
    else:
        write_json(results[0], args.plan_out)
        actions = results[0].get("actions", [])
        provider = targets[0].provider.name
        if results[0].get("applied"):
            print(f"Applied {len(actions)} actions for {provider}.", file=sys.stderr)
        else:
            print(
                f"Planned {len(actions)} actions for {provider}. "
                f"Use --apply --confirm-apply {APPLY_CONFIRMATION} --plan-in <reviewed-plan.json> to execute writes.",
                file=sys.stderr,
            )
    return 0


def command_migrate(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    source_provider = get_provider(args.provider_from, config)
    targets = _target_specs(args, config)
    _reject_unsupported_content(
        args,
        source_provider=source_provider.name,
        target_providers=[target.provider.name for target in targets],
    )
    template = source_provider.export_template(
        ExportOptions(source_id=args.source_id, template=args.template, include_user_overwrites=args.include_user_overwrites)
    )
    if args.redact:
        template = redact_template(template)
    if args.template_out:
        write_json(template.to_dict(), args.template_out)
    problems = template.validate()
    if problems:
        print("Template validation problems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
    validate_apply_safety(
        apply=args.apply,
        confirm_apply=args.confirm_apply,
        validation_problems=problems,
        force_invalid_template=args.force_invalid_template,
    )
    validate_apply_plan_args(args)
    multi_target = len(targets) > 1
    reviewed_batch = (
        _load_reviewed_batch_plan(
            args.plan_in,
            command="migrate",
            source_provider=source_provider.name,
            target_providers=[target.provider.name for target in targets],
        )
        if args.apply and multi_target
        else None
    )
    results = [
        _import_to_target(
            args,
            template=template,
            target=target,
            command="migrate",
            source_provider=source_provider.name,
            reviewed_data=reviewed_batch.get(target.provider.name) if reviewed_batch else None,
            multi_target=multi_target,
        )
        for target in targets
    ]
    if multi_target:
        target_names = [target.provider.name for target in targets]
        write_json(
            _batch_result(
                command="migrate",
                source_provider=source_provider.name,
                target_providers=target_names,
                results=results,
            ),
            args.plan_out,
        )
        action_count = sum(len(result.get("actions", [])) for result in results)
        if args.apply:
            print(f"Migrated {source_provider.name} -> {', '.join(target_names)}: applied {action_count} actions.", file=sys.stderr)
        else:
            print(
                f"Migrated {source_provider.name} -> {', '.join(target_names)}: planned {action_count} actions. "
                f"Use --apply --confirm-apply {APPLY_CONFIRMATION} --plan-in <reviewed-batch-plan.json> to execute writes.",
                file=sys.stderr,
            )
    else:
        write_json(results[0], args.plan_out)
        actions = results[0].get("actions", [])
        target_name = targets[0].provider.name
        if results[0].get("applied"):
            print(f"Migrated {source_provider.name} -> {target_name}: applied {len(actions)} actions.", file=sys.stderr)
        else:
            print(
                f"Migrated {source_provider.name} -> {target_name}: planned {len(actions)} actions. "
                f"Use --apply --confirm-apply {APPLY_CONFIRMATION} --plan-in <reviewed-plan.json> to execute writes.",
                file=sys.stderr,
            )
    return 0


def command_validate(args: argparse.Namespace) -> int:
    template = load_template(args.file)
    problems = template.validate()
    if not problems:
        print("OK: template is valid and privacy-safe by GuildBridge rules.")
        return 0
    for problem in problems:
        print(problem)
    return 2


def command_redact(args: argparse.Namespace) -> int:
    template = load_template(args.file)
    redacted = redact_template(template)
    write_json(redacted.to_dict(), args.out)
    return 0


def command_providers(_: argparse.Namespace) -> int:
    for name, aliases in provider_names().items():
        alias_text = f" ({', '.join(aliases)})" if aliases else ""
        print(f"- {name}{alias_text}")
    return 0


def command_check_access(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    result = check_provider_access(args.provider, args.id, config)
    print(result.summary())
    return 0


def command_content_features(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    capabilities = [get_provider(name, config).content_capabilities() for name in provider_names()]
    if args.format == "json":
        write_json(content_capabilities_document(capabilities), args.out)
    else:
        print(content_capabilities_table(capabilities))
    return 0


def command_routes(args: argparse.Namespace) -> int:
    if args.format == "json":
        write_json(structure_route_document(), args.out)
    else:
        print(structure_routes_table())
    return 0


def _content_options_from_args(
    args: argparse.Namespace,
    *,
    target: TargetSpec,
    channel_map: dict[str, str],
    apply: bool,
) -> ContentImportOptions:
    ferry_parity = bool(getattr(args, "ferry_parity", False))
    raw_parallel_sends = int(getattr(args, "content_parallel_sends", 1) or 1)
    parallel_sends = 3 if ferry_parity and raw_parallel_sends == 1 else raw_parallel_sends
    raw_thread_mode = str(getattr(args, "content_thread_mode", "reference") or "reference")
    if raw_thread_mode not in {"reference", "merge", "channel", "markdown"}:
        raise ValueError("content_thread_mode must be one of: reference, merge, channel, markdown")
    thread_mode = cast(ThreadMode, raw_thread_mode)
    if ferry_parity and thread_mode == "reference":
        thread_mode = "channel"
    return ContentImportOptions(
        apply=apply,
        target_id=target.target_id,
        target_name=target.target_name,
        channel_map=channel_map,
        preserve_authors=not getattr(args, "no_authors", False),
        include_attachments=not getattr(args, "no_attachments", False),
        include_reactions=not getattr(args, "no_reactions", False),
        include_embeds=not getattr(args, "no_embeds", False),
        include_stickers=not getattr(args, "no_stickers", False),
        include_polls=not getattr(args, "no_polls", False),
        include_threads=not getattr(args, "no_threads", False),
        include_custom_emoji=not getattr(args, "no_custom_emoji", False),
        native_attachments=bool(getattr(args, "native_attachments", False)),
        native_embeds=bool(getattr(args, "native_embeds", False)),
        native_replies=bool(getattr(args, "native_replies", False)),
        native_reactions=bool(getattr(args, "native_reactions", False)),
        native_pins=bool(getattr(args, "native_pins", False)),
        native_custom_emoji=bool(getattr(args, "native_custom_emoji", False)),
        native_masquerade=bool(getattr(args, "native_masquerade", False)),
        native_stickers=bool(getattr(args, "native_stickers", False)),
        native_content=bool(getattr(args, "native_content", False) or ferry_parity),
        message_limit=getattr(args, "message_limit", None),
        journal_path=getattr(args, "content_journal_out", None) or (_ferry_artifact_path(target, "content-journal.json") if ferry_parity else None),
        resume_journal=getattr(args, "resume_content_journal", None),
        dead_letter_path=getattr(args, "content_dead_letter_out", None) or (_ferry_artifact_path(target, "dead-letter.json") if ferry_parity else None),
        report_path=getattr(args, "content_report_out", None) or (_ferry_artifact_path(target, "migration-report.json") if ferry_parity else None),
        lock_path=getattr(args, "content_lock_file", None) or (_ferry_artifact_path(target, "content.lock") if ferry_parity else None),
        incremental_state_path=getattr(args, "content_incremental_state", None) or (
            _ferry_artifact_path(target, "incremental-state.json") if ferry_parity else None
        ),
        incremental=bool(getattr(args, "content_incremental", False) or ferry_parity),
        continue_on_error=bool(getattr(args, "content_continue_on_error", False) or ferry_parity),
        max_failures=int(getattr(args, "content_max_failures", 1) or 1),
        parallel_sends=parallel_sends,
        thread_mode=thread_mode,
        thread_archive_dir=getattr(args, "content_thread_archive_dir", None)
        or (_ferry_artifact_path(target, "thread-archives") if ferry_parity else None),
        download_remote_assets=bool(getattr(args, "download_remote_assets", False) or ferry_parity),
    )


def _content_import_to_target(
    args: argparse.Namespace,
    *,
    archive: ContentArchive,
    target: TargetSpec,
    command: str,
    source_provider: str | None = None,
    reviewed_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    archive_hash = content_archive_fingerprint(archive)
    channel_map = load_channel_map(getattr(args, "channel_map", None))
    if args.apply:
        candidate = target.provider.import_content(
            archive,
            _content_options_from_args(args, target=target, channel_map=channel_map, apply=False),
        )
        candidate_plan = _content_plan_metadata(
            command=command,
            provider=target.provider.name,
            source_provider=source_provider,
            archive_name=archive.name,
            archive_hash=archive_hash,
            target_id=target.target_id,
            target_name=target.target_name,
            result=candidate,
        )
        reviewed_plan = (
            validate_reviewed_plan_data(reviewed_data, candidate_plan)
            if reviewed_data is not None
            else validate_reviewed_plan(args.plan_in, candidate_plan)
        )
        plan = apply_result_plan_metadata(candidate_plan, args.plan_in)
        plan["reviewed_action_hash"] = reviewed_plan["action_hash"]
    else:
        plan = None
    result = target.provider.import_content(
        archive,
        _content_options_from_args(args, target=target, channel_map=channel_map, apply=args.apply),
    )
    if plan is None:
        plan = _content_plan_metadata(
            command=command,
            provider=target.provider.name,
            source_provider=source_provider,
            archive_name=archive.name,
            archive_hash=archive_hash,
            target_id=target.target_id,
            target_name=target.target_name,
            result=result,
        )
    return result_to_dict(result, plan=plan)


def _content_batch_or_single_result(
    args: argparse.Namespace,
    *,
    archive: ContentArchive,
    targets: list[TargetSpec],
    command: str,
    source_provider: str | None = None,
    validation_problems: list[str] | None = None,
) -> dict[str, Any]:
    validate_apply_safety(
        apply=args.apply,
        confirm_apply=args.confirm_apply,
        validation_problems=validation_problems or [],
        force_invalid_template=bool(getattr(args, "force_invalid_archive", False)),
    )
    validate_apply_plan_args(args)
    multi_target = len(targets) > 1
    reviewed_batch = (
        _load_reviewed_batch_plan(
            args.plan_in,
            command=command,
            source_provider=source_provider,
            target_providers=[target.provider.name for target in targets],
        )
        if args.apply and multi_target
        else None
    )
    results = [
        _content_import_to_target(
            args,
            archive=archive,
            target=target,
            command=command,
            source_provider=source_provider,
            reviewed_data=reviewed_batch.get(target.provider.name) if reviewed_batch else None,
        )
        for target in targets
    ]
    if not multi_target:
        return results[0]
    return _batch_result(
        command=command,
        source_provider=source_provider,
        target_providers=[target.provider.name for target in targets],
        results=results,
    )


def _resolve_discord_chat_export_path(args: argparse.Namespace) -> str | Path:
    discord_chat_export = getattr(args, "discord_chat_export", None)
    exporter_bin = getattr(args, "discord_chat_exporter_bin", None)
    download_exporter = bool(getattr(args, "download_discord_chat_exporter", False))
    if discord_chat_export:
        if exporter_bin or download_exporter:
            raise ValueError(
                "Use --discord-chat-export for an existing export, or use DiscordChatExporter execution options, not both."
            )
        return discord_chat_export
    if download_exporter:
        if exporter_bin:
            raise ValueError("Use either --discord-chat-exporter-bin or --download-discord-chat-exporter, not both.")
        exporter_bin = download_discord_chat_exporter(
            DiscordChatExporterBootstrapOptions(
                version=getattr(args, "discord_chat_exporter_version", "latest") or "latest",
                install_dir=getattr(args, "discord_chat_exporter_install_dir", None),
                timeout_seconds=int(getattr(args, "discord_export_timeout", 3600) or 3600),
                sha256=getattr(args, "discord_chat_exporter_sha256", None),
            )
        )
    if not exporter_bin:
        raise ValueError(
            "Content export requires --discord-chat-export <file-or-folder> or "
            "--discord-chat-exporter-bin with --source-id. Use --download-discord-chat-exporter to fetch a managed DCE CLI."
        )
    source_id = (getattr(args, "source_id", None) or "").strip()
    if not source_id:
        raise ValueError("--discord-chat-exporter-bin requires --source-id with the Discord guild/server id.")
    return run_discord_chat_exporter(
        DiscordChatExporterOptions(
            exporter_bin=exporter_bin,
            guild_id=source_id,
            output_path=getattr(args, "discord_export_out", None),
            token_env=getattr(args, "discord_token_env", "DISCORD_TOKEN") or "DISCORD_TOKEN",
            export_format=getattr(args, "discord_export_format", "Json") or "Json",
            timeout_seconds=int(getattr(args, "discord_export_timeout", 3600) or 3600),
        )
    )


def command_content_export(args: argparse.Namespace) -> int:
    archive = load_discord_chat_export(_resolve_discord_chat_export_path(args))
    problems = archive.validate()
    if problems:
        archive.warnings.extend(problems)
    write_json(archive.to_dict(), args.out)
    print(f"Exported {len(archive.messages)} messages from {len(archive.channels)} channel(s).", file=sys.stderr)
    return 0


def command_content_import(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    archive = load_content_archive(args.file)
    problems = archive.validate()
    if problems:
        print("Content archive validation problems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
    targets = _target_specs(args, config)
    result = _content_batch_or_single_result(
        args,
        archive=archive,
        targets=targets,
        command="content-import",
        validation_problems=problems,
    )
    write_json(result, args.plan_out)
    action_count = result.get("action_count") or len(result.get("actions", []))
    print(f"{'Applied' if args.apply else 'Planned'} {action_count} content action(s).", file=sys.stderr)
    return 0


def command_content_migrate(args: argparse.Namespace) -> int:
    source_provider = getattr(args, "provider_from", "discord")
    config = RuntimeConfig.from_env()
    content_archive = getattr(args, "content_archive", None)
    if content_archive:
        archive = load_content_archive(content_archive)
        archive_source = archive.source.platform.strip().lower()
        if archive_source and archive_source != "unknown" and archive_source != source_provider:
            raise ValueError(
                f"Content archive source is {archive.source.platform!r}, which does not match --from {source_provider!r}."
            )
    elif source_provider == "discord":
        archive = load_discord_chat_export(_resolve_discord_chat_export_path(args))
    else:
        raise ValueError(
            f"Content migrate from {source_provider!r} requires --content-archive with a GuildBridge content archive. "
            "Direct offline export conversion is currently available only for DiscordChatExporter."
        )
    problems = archive.validate()
    if problems:
        print("Content archive validation problems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
    targets = _target_specs(args, config)
    result = _content_batch_or_single_result(
        args,
        archive=archive,
        targets=targets,
        command="content-migrate",
        source_provider=source_provider,
        validation_problems=problems,
    )
    write_json(result, args.plan_out)
    action_count = result.get("action_count") or len(result.get("actions", []))
    print(f"{'Applied' if args.apply else 'Planned'} {action_count} content migration action(s).", file=sys.stderr)
    return 0


def command_platforms(args: argparse.Namespace) -> int:
    if args.check:
        checks = runtime_check()
        evaluation = evaluate_runtime_check(checks, args.require)
        for key, value in checks.items():
            print(f"{key}: {value}")
        print(f"required_target: {evaluation.target}")
        print(f"check_ready: {evaluation.ready}")
        if evaluation.failures:
            print("failures:")
            for failure in evaluation.failures:
                print(f"- {failure}")
        if evaluation.warnings:
            print("warnings:")
            for warning in evaluation.warnings:
                print(f"- {warning}")
        return 0 if evaluation.ready else 1
    for supported in SUPPORTED_PLATFORMS:
        managers = ", ".join(supported.package_managers)
        print(
            f"- {supported.name} [{supported.family}] package managers: {managers}; "
            f"Tk: {supported.tk_package}; {supported.support_summary}"
        )
    return 0


def _add_content_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--to",
        dest="provider_to",
        action="append",
        required=True,
        help="target provider; repeat or comma-separate for multiple targets",
    )
    parser.add_argument(
        "--target-id",
        action="append",
        help="existing target guild/server/space id; repeat as provider=value for provider-specific targets",
    )
    parser.add_argument(
        "--target-name",
        action="append",
        help="target community name; repeat as provider=value for provider-specific targets",
    )
    parser.add_argument(
        "--channel-map",
        help="JSON mapping from content archive channel ids to target channel ids; can also be a GuildBridge plan result",
    )
    parser.add_argument("--plan-out", default="-", help="write content plan/result JSON path or - for stdout")
    parser.add_argument("--plan-in", help="reviewed dry-run content plan required before --apply writes are allowed")
    parser.add_argument("--apply", action="store_true", help="perform content writes after a reviewed dry-run plan")
    parser.add_argument(
        "--confirm-apply",
        help=f"must be set to {APPLY_CONFIRMATION!r} when --apply is used",
    )
    parser.add_argument(
        "--force-invalid-archive",
        action="store_true",
        help="allow --apply despite content archive validation problems after manual review",
    )
    parser.add_argument("--message-limit", type=int, help="limit the number of messages planned or imported")
    parser.add_argument("--no-authors", action="store_true", help="do not include archived author names in formatted messages")
    parser.add_argument("--no-attachments", action="store_true", help="do not include attachment references in formatted messages")
    parser.add_argument("--no-reactions", action="store_true", help="do not include reaction summaries in formatted messages")
    parser.add_argument("--no-embeds", action="store_true", help="do not include embed summaries in formatted messages")
    parser.add_argument("--no-stickers", action="store_true", help="do not include sticker references in formatted messages")
    parser.add_argument("--no-polls", action="store_true", help="do not include poll summaries in formatted messages")
    parser.add_argument("--no-threads", action="store_true", help="do not include thread/forum references in formatted messages")
    parser.add_argument("--no-custom-emoji", action="store_true", help="do not include custom emoji summaries in formatted messages")
    parser.add_argument(
        "--native-content",
        action="store_true",
        help="use provider-native content features where supported instead of text-only fallbacks",
    )
    parser.add_argument(
        "--ferry-parity",
        action="store_true",
        help=(
            "enable Discord-stoat-ferry-style defaults: native content, remote media downloads, thread-channel mode, "
            "parallel sends, incremental state, dead letters, reports, lock files, and continue-on-error"
        ),
    )
    parser.add_argument(
        "--download-remote-assets",
        action="store_true",
        help="download remote attachment/icon/banner URLs into .guildbridge before provider-native uploads",
    )
    parser.add_argument("--native-attachments", action="store_true", help="upload local attachments natively where supported")
    parser.add_argument("--native-embeds", action="store_true", help="send embeds natively where supported")
    parser.add_argument("--native-replies", action="store_true", help="link replies natively where supported")
    parser.add_argument("--native-reactions", action="store_true", help="apply reactions natively where supported")
    parser.add_argument("--native-pins", action="store_true", help="pin migrated messages natively where supported")
    parser.add_argument("--native-custom-emoji", action="store_true", help="create custom emoji natively where supported")
    parser.add_argument("--native-masquerade", action="store_true", help="send messages with original author display names where supported")
    parser.add_argument("--native-stickers", action="store_true", help="upload local sticker media as native attachments where supported")
    parser.add_argument("--content-journal-out", help="write a content apply journal JSON file")
    parser.add_argument("--resume-content-journal", help="resume content apply safety from a previous content apply journal")
    parser.add_argument("--content-dead-letter-out", help="write failed content actions to this JSON file")
    parser.add_argument("--content-report-out", help="write a content migration report JSON file")
    parser.add_argument("--content-lock-file", help="lock file used to prevent concurrent content writes to the same target")
    parser.add_argument("--content-incremental-state", help="JSON state file used to skip content actions already applied earlier")
    parser.add_argument("--content-incremental", action="store_true", help="skip actions present in --content-incremental-state")
    parser.add_argument("--content-continue-on-error", action="store_true", help="continue content import after failed messages and write dead letters")
    parser.add_argument("--content-max-failures", type=int, default=1, help="stop after this many consecutive content failures")
    parser.add_argument(
        "--content-parallel-sends",
        type=int,
        default=1,
        help="send multiple source channels concurrently while preserving message order inside each channel",
    )
    parser.add_argument(
        "--content-thread-mode",
        choices=("reference", "merge", "channel", "markdown"),
        default="reference",
        help=(
            "how to handle thread/forum messages: reference keeps text references, merge folds them into the parent channel, "
            "channel routes them through mapped thread ids, and markdown writes local thread archive files"
        ),
    )
    parser.add_argument(
        "--content-thread-archive-dir",
        help="directory for local markdown thread/forum archives when --content-thread-mode markdown is used",
    )


def _add_discord_content_export_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--discord-chat-export",
        help="existing DiscordChatExporter JSON file or folder to convert",
    )
    parser.add_argument("--source-id", help="Discord guild/server id when running DiscordChatExporter")
    parser.add_argument(
        "--discord-chat-exporter-bin",
        help="path to a locally installed DiscordChatExporter.Cli executable to run before conversion",
    )
    parser.add_argument(
        "--download-discord-chat-exporter",
        action="store_true",
        help="download and cache DiscordChatExporter.Cli for this platform before exporting; requires --source-id",
    )
    parser.add_argument(
        "--discord-chat-exporter-version",
        default="latest",
        help="DiscordChatExporter release tag to download, or latest; default: latest",
    )
    parser.add_argument(
        "--discord-chat-exporter-install-dir",
        help="directory used for managed DiscordChatExporter downloads; default: .guildbridge/tools/discord-chat-exporter",
    )
    parser.add_argument(
        "--discord-chat-exporter-sha256",
        help="expected SHA-256 for the managed DiscordChatExporter asset; required when release metadata has no digest",
    )
    parser.add_argument(
        "--discord-token-env",
        default="DISCORD_TOKEN",
        help="environment variable containing the Discord token for DiscordChatExporter; default: DISCORD_TOKEN",
    )
    parser.add_argument(
        "--discord-export-out",
        help="DiscordChatExporter JSON output file/folder; defaults under .guildbridge/content/discord-chat-exporter",
    )
    parser.add_argument("--discord-export-format", default="Json", help="DiscordChatExporter format argument; default: Json")
    parser.add_argument("--discord-export-timeout", type=int, default=3600, help="DiscordChatExporter timeout in seconds")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guildbridge",
        description="Privacy-first server/community template importer/exporter for Discord, Fluxer, Stoat, Matrix/Element, Rocket.Chat, and Mumble.",
    )
    parser.add_argument("--version", action="store_true", help="show version and exit")
    sub = parser.add_subparsers(dest="command")

    p_export = sub.add_parser("export", help="export a provider server/community to a neutral JSON template")
    p_export.add_argument(
        "--from",
        dest="provider_from",
        required=True,
        help="source provider: discord, fluxer, stoat, spacebar, daccord, matrix/element, rocket.chat, mumble, mattermost, zulip",
    )
    p_export.add_argument("--source-id", help="source guild/server/space id")
    p_export.add_argument("--template", help="provider template URL/code, currently useful for Discord")
    p_export.add_argument("--out", default="community.template.json", help="output template JSON path or - for stdout")
    p_export.add_argument("--include-user-overwrites", action="store_true", help="request user/member overwrite diagnostics; unsafe user targets are still dropped")
    p_export.add_argument("--include-content", action="store_true", help="opt into private content migration features when implemented")
    p_export.add_argument(
        "--content-feature",
        action="append",
        choices=CONTENT_FEATURES,
        help="limit optional content migration to one feature; repeat for multiple features",
    )
    p_export.set_defaults(func=command_export)

    p_import = sub.add_parser("import", help="import a neutral JSON template into a provider")
    p_import.add_argument(
        "--to",
        dest="provider_to",
        action="append",
        required=True,
        help="target provider; repeat or comma-separate for multiple targets",
    )
    p_import.add_argument("--file", required=True, help="neutral template JSON file")
    p_import.add_argument(
        "--target-id",
        action="append",
        help="existing target guild/server/space id; repeat as provider=value for provider-specific targets",
    )
    p_import.add_argument(
        "--target-name",
        action="append",
        help="name to use if the target provider creates a new community; repeat as provider=value for provider-specific names",
    )
    p_import.add_argument("--apply", action="store_true", help="perform write actions; by default this only prints a dry-run plan")
    p_import.add_argument(
        "--confirm-apply",
        help=f"must be set to {APPLY_CONFIRMATION!r} when --apply is used",
    )
    p_import.add_argument(
        "--force-invalid-template",
        action="store_true",
        help="allow --apply despite template validation problems after manual review",
    )
    p_import.add_argument("--plan-out", default="-", help="write action plan/result JSON path or - for stdout")
    p_import.add_argument("--plan-in", help="reviewed dry-run plan required before --apply writes are allowed")
    p_import.add_argument("--journal-out", help="write an apply journal JSON file; defaults under .guildbridge/journals when --apply is used")
    p_import.add_argument("--resume-journal", help="validate this apply run against a failed or interrupted journal before writing")
    p_import.add_argument("--audit-log-reason", help="optional audit-log reason where supported")
    p_import.add_argument("--redact", action="store_true", help="redact template before import")
    p_import.add_argument("--include-content", action="store_true", help="opt into private content migration features when implemented")
    p_import.add_argument(
        "--content-feature",
        action="append",
        choices=CONTENT_FEATURES,
        help="limit optional content migration to one feature; repeat for multiple features",
    )
    p_import.set_defaults(func=command_import)

    p_migrate = sub.add_parser("migrate", help="export then import in one command")
    p_migrate.add_argument("--from", dest="provider_from", required=True, help="source provider")
    p_migrate.add_argument("--to", dest="provider_to", action="append", required=True, help="target provider; repeat or comma-separate for multiple targets")
    p_migrate.add_argument("--source-id", help="source guild/server/space id")
    p_migrate.add_argument("--template", help="provider template URL/code, currently useful for Discord")
    p_migrate.add_argument("--target-id", action="append", help="existing target guild/server/space id; repeat as provider=value for provider-specific targets")
    p_migrate.add_argument("--target-name", action="append", help="name to use if the target provider creates a new community; repeat as provider=value for provider-specific names")
    p_migrate.add_argument("--template-out", help="optionally save the neutral template JSON")
    p_migrate.add_argument("--plan-out", default="-", help="write action plan/result JSON path or - for stdout")
    p_migrate.add_argument("--plan-in", help="reviewed dry-run plan required before --apply writes are allowed")
    p_migrate.add_argument("--journal-out", help="write an apply journal JSON file; defaults under .guildbridge/journals when --apply is used")
    p_migrate.add_argument("--resume-journal", help="validate this apply run against a failed or interrupted journal before writing")
    p_migrate.add_argument("--include-user-overwrites", action="store_true", help="request user/member overwrite diagnostics; unsafe user targets are still dropped")
    p_migrate.add_argument("--include-content", action="store_true", help="opt into private content migration features when implemented")
    p_migrate.add_argument(
        "--content-feature",
        action="append",
        choices=CONTENT_FEATURES,
        help="limit optional content migration to one feature; repeat for multiple features",
    )
    p_migrate.add_argument("--redact", action="store_true", default=True, help="redact template before import; enabled by default")
    p_migrate.add_argument("--apply", action="store_true", help="perform write actions; by default this only prints a dry-run plan")
    p_migrate.add_argument(
        "--confirm-apply",
        help=f"must be set to {APPLY_CONFIRMATION!r} when --apply is used",
    )
    p_migrate.add_argument(
        "--force-invalid-template",
        action="store_true",
        help="allow --apply despite template validation problems after manual review",
    )
    p_migrate.add_argument("--audit-log-reason", help="optional audit-log reason where supported")
    p_migrate.set_defaults(func=command_migrate)

    p_validate = sub.add_parser("validate", help="validate a neutral JSON template")
    p_validate.add_argument("file")
    p_validate.set_defaults(func=command_validate)

    p_redact = sub.add_parser("redact", help="remove non-structural/private fields from a template")
    p_redact.add_argument("file")
    p_redact.add_argument("--out", default="redacted.template.json")
    p_redact.set_defaults(func=command_redact)

    p_providers = sub.add_parser("providers", help="list providers and aliases")
    p_providers.set_defaults(func=command_providers)

    p_check_access = sub.add_parser("check-access", help="check read access to a provider server/community")
    p_check_access.add_argument("--provider", required=True, help="provider to check")
    p_check_access.add_argument("--id", required=True, help="source or target server/guild/community id to read")
    p_check_access.set_defaults(func=command_check_access)

    p_content = sub.add_parser("content-features", help="show optional content migration feature coverage")
    p_content.add_argument("--format", choices=("text", "json"), default="text", help="output format")
    p_content.add_argument("--out", default="-", help="JSON output path when --format json is used")
    p_content.set_defaults(func=command_content_features)

    p_routes = sub.add_parser("routes", help="show supported structural provider migration routes")
    p_routes.add_argument("--format", choices=("text", "json"), default="text", help="output format")
    p_routes.add_argument("--out", default="-", help="JSON output path when --format json is used")
    p_routes.set_defaults(func=command_routes)

    p_content_export = sub.add_parser(
        "content-export",
        help="convert an offline provider content export into a GuildBridge content archive",
    )
    _add_discord_content_export_args(p_content_export)
    p_content_export.add_argument("--out", default="community.content.json", help="output content archive JSON path or - for stdout")
    p_content_export.set_defaults(func=command_content_export)

    p_content_import = sub.add_parser(
        "content-import",
        help="plan or apply a GuildBridge content archive into one or more providers",
    )
    p_content_import.add_argument("--file", required=True, help="GuildBridge content archive JSON file")
    _add_content_target_args(p_content_import)
    p_content_import.set_defaults(func=command_content_import)

    p_content_migrate = sub.add_parser(
        "content-migrate",
        help="convert an offline source export and plan or apply it into one or more providers",
    )
    p_content_migrate.add_argument(
        "--from",
        dest="provider_from",
        choices=tuple(provider_names()),
        default="discord",
        help="content archive source provider; Discord can also be converted directly from DiscordChatExporter JSON",
    )
    p_content_migrate.add_argument(
        "--content-archive",
        help="existing GuildBridge content archive JSON; required for non-Discord source providers",
    )
    _add_discord_content_export_args(p_content_migrate)
    _add_content_target_args(p_content_migrate)
    p_content_migrate.set_defaults(func=command_content_migrate)

    p_platforms = sub.add_parser("platforms", help="list supported operating systems")
    p_platforms.add_argument("--check", action="store_true", help="check the current runtime for GuildBridge support")
    p_platforms.add_argument(
        "--require",
        choices=CHECK_TARGETS,
        default="cli",
        help="capability required by --check",
    )
    p_platforms.set_defaults(func=command_platforms)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        from guildbridge import __version__

        print(__version__)
        return 0
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - top-level CLI boundary converts unexpected errors into sanitized diagnostics.
        print(format_error_report(exc), file=sys.stderr)
        return 1

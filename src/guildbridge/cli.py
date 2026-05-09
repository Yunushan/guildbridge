from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from guildbridge.config import RuntimeConfig
from guildbridge.diagnostics import format_error_report
from guildbridge.journal import (
    ApplyJournal,
    ApplyJournalContext,
    default_journal_path,
    template_fingerprint,
    validate_resume_journal,
)
from guildbridge.models import CommunityTemplate
from guildbridge.plan import (
    apply_result_plan_metadata,
    build_plan_context,
    build_plan_metadata,
    result_to_dict,
    validate_reviewed_plan,
)
from guildbridge.platforms import CHECK_TARGETS, SUPPORTED_PLATFORMS, evaluate_runtime_check, runtime_check
from guildbridge.privacy import redact_template
from guildbridge.providers import get_provider, provider_names
from guildbridge.providers.base import ExportOptions, ImportOptions
from guildbridge.safety import APPLY_CONFIRMATION, validate_apply_safety


def load_template(path: str | Path) -> CommunityTemplate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CommunityTemplate.from_dict(data)


def write_json(data: dict[str, Any], path: str | None) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if not path or path == "-":
        print(text)
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def prepare_apply_journal(
    args: argparse.Namespace,
    *,
    command: str,
    provider: str,
    template: CommunityTemplate,
    source_provider: str | None = None,
    reviewed_plan_hash: str | None = None,
) -> ApplyJournal | None:
    journal_out = getattr(args, "journal_out", None)
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
        target_id=getattr(args, "target_id", None),
        target_name=getattr(args, "target_name", None),
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


def command_export(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    provider = get_provider(args.provider_from, config)
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
    provider = get_provider(args.provider_to, config)
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
    plan_context = build_plan_context(
        command="import",
        provider=provider.name,
        template=template,
        target_id=args.target_id,
        target_name=args.target_name,
    )
    reviewed_plan_hash: str | None = None
    output_plan: dict[str, Any] | None = None
    if args.apply:
        candidate = provider.import_template(
            template,
            ImportOptions(
                target_id=args.target_id,
                target_name=args.target_name,
                apply=False,
                audit_log_reason=args.audit_log_reason,
            ),
        )
        candidate_plan = build_plan_metadata(plan_context, candidate)
        reviewed_plan = validate_reviewed_plan(args.plan_in, candidate_plan)
        reviewed_plan_hash = str(reviewed_plan["action_hash"])
        output_plan = apply_result_plan_metadata(candidate_plan, args.plan_in)
    journal = prepare_apply_journal(
        args,
        command="import",
        provider=provider.name,
        template=template,
        reviewed_plan_hash=reviewed_plan_hash,
    )
    try:
        result = provider.import_template(
            template,
            ImportOptions(
                target_id=args.target_id,
                target_name=args.target_name,
                apply=args.apply,
                audit_log_reason=args.audit_log_reason,
                journal=journal,
            ),
        )
    except Exception as exc:
        if journal:
            journal.fail(exc)
        raise
    if output_plan is None:
        output_plan = build_plan_metadata(plan_context, result)
    if journal:
        journal.finish(result)
    write_json(result_to_dict(result, plan=output_plan), args.plan_out)
    if result.applied:
        print(f"Applied {len(result.actions)} actions for {provider.name}.", file=sys.stderr)
    else:
        print(
            f"Planned {len(result.actions)} actions for {provider.name}. "
            f"Use --apply --confirm-apply {APPLY_CONFIRMATION} --plan-in <reviewed-plan.json> to execute writes.",
            file=sys.stderr,
        )
    return 0


def command_migrate(args: argparse.Namespace) -> int:
    config = RuntimeConfig.from_env()
    source_provider = get_provider(args.provider_from, config)
    target_provider = get_provider(args.provider_to, config)
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
    plan_context = build_plan_context(
        command="migrate",
        provider=target_provider.name,
        source_provider=source_provider.name,
        template=template,
        target_id=args.target_id,
        target_name=args.target_name,
    )
    reviewed_plan_hash: str | None = None
    output_plan: dict[str, Any] | None = None
    if args.apply:
        candidate = target_provider.import_template(
            template,
            ImportOptions(
                target_id=args.target_id,
                target_name=args.target_name,
                apply=False,
                audit_log_reason=args.audit_log_reason,
            ),
        )
        candidate_plan = build_plan_metadata(plan_context, candidate)
        reviewed_plan = validate_reviewed_plan(args.plan_in, candidate_plan)
        reviewed_plan_hash = str(reviewed_plan["action_hash"])
        output_plan = apply_result_plan_metadata(candidate_plan, args.plan_in)
    journal = prepare_apply_journal(
        args,
        command="migrate",
        provider=target_provider.name,
        source_provider=source_provider.name,
        template=template,
        reviewed_plan_hash=reviewed_plan_hash,
    )
    try:
        result = target_provider.import_template(
            template,
            ImportOptions(
                target_id=args.target_id,
                target_name=args.target_name,
                apply=args.apply,
                audit_log_reason=args.audit_log_reason,
                journal=journal,
            ),
        )
    except Exception as exc:
        if journal:
            journal.fail(exc)
        raise
    if output_plan is None:
        output_plan = build_plan_metadata(plan_context, result)
    if journal:
        journal.finish(result)
    write_json(result_to_dict(result, plan=output_plan), args.plan_out)
    if result.applied:
        print(f"Migrated {source_provider.name} -> {target_provider.name}: applied {len(result.actions)} actions.", file=sys.stderr)
    else:
        print(
            f"Migrated {source_provider.name} -> {target_provider.name}: planned {len(result.actions)} actions. "
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guildbridge",
        description="Privacy-first server/community template importer/exporter for Discord, Fluxer, Stoat, Matrix/Element, Rocket.Chat, and Mumble.",
    )
    parser.add_argument("--version", action="store_true", help="show version and exit")
    sub = parser.add_subparsers(dest="command")

    p_export = sub.add_parser("export", help="export a provider server/community to a neutral JSON template")
    p_export.add_argument("--from", dest="provider_from", required=True, help="source provider: discord, fluxer, stoat, matrix/element, rocket.chat, mumble")
    p_export.add_argument("--source-id", help="source guild/server/space id")
    p_export.add_argument("--template", help="provider template URL/code, currently useful for Discord")
    p_export.add_argument("--out", default="community.template.json", help="output template JSON path or - for stdout")
    p_export.add_argument("--include-user-overwrites", action="store_true", help="request user/member overwrite diagnostics; unsafe user targets are still dropped")
    p_export.set_defaults(func=command_export)

    p_import = sub.add_parser("import", help="import a neutral JSON template into a provider")
    p_import.add_argument("--to", dest="provider_to", required=True, help="target provider: discord, fluxer, stoat, matrix/element, rocket.chat, mumble")
    p_import.add_argument("--file", required=True, help="neutral template JSON file")
    p_import.add_argument("--target-id", help="existing target guild/server/space id; optional for providers that can create a new target")
    p_import.add_argument("--target-name", help="name to use if the target provider creates a new community")
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
    p_import.set_defaults(func=command_import)

    p_migrate = sub.add_parser("migrate", help="export then import in one command")
    p_migrate.add_argument("--from", dest="provider_from", required=True, help="source provider")
    p_migrate.add_argument("--to", dest="provider_to", required=True, help="target provider")
    p_migrate.add_argument("--source-id", help="source guild/server/space id")
    p_migrate.add_argument("--template", help="provider template URL/code, currently useful for Discord")
    p_migrate.add_argument("--target-id", help="existing target guild/server/space id")
    p_migrate.add_argument("--target-name", help="name to use if the target provider creates a new community")
    p_migrate.add_argument("--template-out", help="optionally save the neutral template JSON")
    p_migrate.add_argument("--plan-out", default="-", help="write action plan/result JSON path or - for stdout")
    p_migrate.add_argument("--plan-in", help="reviewed dry-run plan required before --apply writes are allowed")
    p_migrate.add_argument("--journal-out", help="write an apply journal JSON file; defaults under .guildbridge/journals when --apply is used")
    p_migrate.add_argument("--resume-journal", help="validate this apply run against a failed or interrupted journal before writing")
    p_migrate.add_argument("--include-user-overwrites", action="store_true", help="request user/member overwrite diagnostics; unsafe user targets are still dropped")
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
    except Exception as exc:
        print(format_error_report(exc), file=sys.stderr)
        return 1

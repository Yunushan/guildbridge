from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from guildbridge.config import RuntimeConfig
from guildbridge.models import CommunityTemplate
from guildbridge.privacy import redact_template
from guildbridge.providers import get_provider, provider_names
from guildbridge.providers.base import ExportOptions, ImportOptions


def load_template(path: str | Path) -> CommunityTemplate:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return CommunityTemplate.from_dict(data)


def write_json(data: Dict[str, Any], path: Optional[str]) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    if not path or path == "-":
        print(text)
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


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
        print("Template validation warnings:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
    result = provider.import_template(
        template,
        ImportOptions(
            target_id=args.target_id,
            target_name=args.target_name,
            apply=args.apply,
            audit_log_reason=args.audit_log_reason,
        ),
    )
    write_json(result.to_dict(), args.plan_out)
    print(
        f"{'Applied' if result.applied else 'Planned'} {len(result.actions)} actions for {provider.name}. Use --apply to execute writes.",
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
    result = target_provider.import_template(
        template,
        ImportOptions(
            target_id=args.target_id,
            target_name=args.target_name,
            apply=args.apply,
            audit_log_reason=args.audit_log_reason,
        ),
    )
    write_json(result.to_dict(), args.plan_out)
    print(
        f"Migrated {source_provider.name} -> {target_provider.name}: {'applied' if result.applied else 'planned'} {len(result.actions)} actions.",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guildbridge",
        description="Privacy-first server/community template importer/exporter for Discord, Fluxer, Stoat, and Matrix/Element.",
    )
    parser.add_argument("--version", action="store_true", help="show version and exit")
    sub = parser.add_subparsers(dest="command")

    p_export = sub.add_parser("export", help="export a provider server/community to a neutral JSON template")
    p_export.add_argument("--from", dest="provider_from", required=True, help="source provider: discord, fluxer, stoat, matrix/element")
    p_export.add_argument("--source-id", help="source guild/server/space id")
    p_export.add_argument("--template", help="provider template URL/code, currently useful for Discord")
    p_export.add_argument("--out", default="community.template.json", help="output template JSON path or - for stdout")
    p_export.add_argument("--include-user-overwrites", action="store_true", help="include anonymized user/member overwrites; off by default")
    p_export.set_defaults(func=command_export)

    p_import = sub.add_parser("import", help="import a neutral JSON template into a provider")
    p_import.add_argument("--to", dest="provider_to", required=True, help="target provider: discord, fluxer, stoat, matrix/element")
    p_import.add_argument("--file", required=True, help="neutral template JSON file")
    p_import.add_argument("--target-id", help="existing target guild/server/space id; optional for providers that can create a new target")
    p_import.add_argument("--target-name", help="name to use if the target provider creates a new community")
    p_import.add_argument("--apply", action="store_true", help="perform write actions; by default this only prints a dry-run plan")
    p_import.add_argument("--plan-out", default="-", help="write action plan/result JSON path or - for stdout")
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
    p_migrate.add_argument("--include-user-overwrites", action="store_true", help="include anonymized user/member overwrites; off by default")
    p_migrate.add_argument("--redact", action="store_true", default=True, help="redact template before import; enabled by default")
    p_migrate.add_argument("--apply", action="store_true", help="perform write actions; by default this only prints a dry-run plan")
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

    return parser


def main(argv: Optional[list[str]] = None) -> int:
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
        print(f"guildbridge: error: {exc}", file=sys.stderr)
        return 1

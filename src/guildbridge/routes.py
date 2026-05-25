from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from guildbridge.providers import provider_names as registered_provider_names

STRUCTURE_ROUTE_SCHEMA = "guildbridge.structure-routes.v1"


def canonical_provider_names(names: Sequence[str] | None = None) -> list[str]:
    if names is not None:
        return sorted({name.strip().lower() for name in names if name.strip()})
    return sorted(registered_provider_names())


def structure_route_document(names: Sequence[str] | None = None) -> dict[str, Any]:
    providers = canonical_provider_names(names)
    aliases = registered_provider_names()
    routes = [
        {
            "from": source,
            "to": target,
            "status": "supported",
            "route_type": "structure-template",
            "multi_target": True,
            "same_provider_clone": source == target,
        }
        for source in providers
        for target in providers
    ]
    return {
        "schema": STRUCTURE_ROUTE_SCHEMA,
        "route_type": "structure-template",
        "provider_count": len(providers),
        "route_count": len(routes),
        "providers": providers,
        "provider_aliases": {provider: list(aliases.get(provider, ())) for provider in providers},
        "multi_target": {
            "supported": True,
            "cli": "Repeat --to or pass comma-separated targets.",
            "gui": "Select one source and one or more destinations in the To list.",
        },
        "routes": routes,
        "notes": [
            "Routes cover privacy-safe structure/template migration through community.template.json.",
            "Provider APIs can still require a token, an existing target ID, or an admin bridge.",
            "Optional message/content migration is separate from structure routes.",
        ],
    }


def structure_routes_table(names: Sequence[str] | None = None) -> str:
    document = structure_route_document(names)
    providers = [str(provider) for provider in document["providers"]]
    alias_lines = [
        f"- {provider}: {', '.join(aliases) if aliases else '(none)'}"
        for provider, aliases in document["provider_aliases"].items()
    ]
    route_lines = [f"- {source} -> {', '.join(providers)}" for source in providers]
    return "\n".join(
        [
            "Structural provider route support",
            "",
            "Every listed source can migrate to one or more listed targets through community.template.json.",
            "Use repeated --to values or a comma-separated --to value for multi-destination runs.",
            "",
            f"Providers: {', '.join(providers)}",
            f"Routes: {document['route_count']}",
            "",
            "Provider aliases:",
            *alias_lines,
            "",
            "Route matrix:",
            *route_lines,
        ]
    )

from __future__ import annotations

from dataclasses import dataclass

from guildbridge.config import RuntimeConfig
from guildbridge.providers import get_provider
from guildbridge.providers.base import ExportOptions


@dataclass(frozen=True)
class AccessCheckResult:
    provider: str
    resource_id: str
    name: str
    roles: int
    categories: int
    channels: int
    warnings: int

    def summary(self) -> str:
        return (
            f"{self.provider} access ok: {self.name!r} "
            f"({self.roles} roles, {self.categories} categories, {self.channels} channels, {self.warnings} warnings)"
        )


def check_provider_access(provider_name: str, resource_id: str, config: RuntimeConfig) -> AccessCheckResult:
    cleaned_id = resource_id.strip()
    if not cleaned_id:
        raise ValueError("--id is required for access checks.")
    provider = get_provider(provider_name, config)
    template = provider.export_template(ExportOptions(source_id=cleaned_id))
    return AccessCheckResult(
        provider=provider.name,
        resource_id=cleaned_id,
        name=template.name,
        roles=len(template.roles),
        categories=len(template.categories),
        channels=len(template.channels),
        warnings=len(template.warnings),
    )

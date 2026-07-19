from __future__ import annotations

import pytest

from guildbridge.access import check_provider_access
from guildbridge.config import RuntimeConfig
from guildbridge.models import Category, Channel, CommunityTemplate, Role
from guildbridge.providers.base import ExportOptions


class AccessProvider:
    name = "test-provider"

    def __init__(self) -> None:
        self.options: ExportOptions | None = None

    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        self.options = options
        return CommunityTemplate(
            name="Migrated community",
            roles=[Role(id="role", name="Role")],
            categories=[Category(id="category", name="Category")],
            channels=[Channel(id="channel", name="general", type="text")],
            warnings=["A non-fatal provider warning"],
        )


def test_access_check_exports_trimmed_resource_and_summarizes_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = AccessProvider()
    monkeypatch.setattr("guildbridge.access.get_provider", lambda _name, _config: provider)

    result = check_provider_access("discord", "  guild-123  ", RuntimeConfig())

    assert provider.options is not None
    assert provider.options.source_id == "guild-123"
    assert result.provider == "test-provider"
    assert result.resource_id == "guild-123"
    assert (result.roles, result.categories, result.channels, result.warnings) == (1, 1, 1, 1)
    assert result.summary() == "test-provider access ok: 'Migrated community' (1 roles, 1 categories, 1 channels, 1 warnings)"


def test_access_check_rejects_missing_resource_id() -> None:
    with pytest.raises(ValueError, match="--id is required for access checks"):
        check_provider_access("discord", " \t ", RuntimeConfig())

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from guildbridge.config import RuntimeConfig
from guildbridge.models import CommunityTemplate, ImportResult


@dataclass
class ExportOptions:
    source_id: str | None = None
    template: str | None = None
    include_user_overwrites: bool = False


@dataclass
class ImportOptions:
    target_id: str | None = None
    target_name: str | None = None
    apply: bool = False
    audit_log_reason: str | None = None


class Provider(ABC):
    name: str
    aliases: tuple[str, ...] = ()

    def __init__(self, config: RuntimeConfig):
        self.config = config

    @abstractmethod
    def export_template(self, options: ExportOptions) -> CommunityTemplate:
        raise NotImplementedError

    @abstractmethod
    def import_template(self, template: CommunityTemplate, options: ImportOptions) -> ImportResult:
        raise NotImplementedError

    @staticmethod
    def supported_warning() -> str:
        return "Messages, members, DMs, and user-specific permission overwrites are intentionally not exported."

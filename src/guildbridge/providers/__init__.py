from __future__ import annotations

from guildbridge.config import RuntimeConfig

from .base import Provider
from .discord import DiscordProvider
from .fluxer import FluxerProvider
from .matrix import MatrixProvider
from .stoat import StoatProvider

PROVIDER_CLASSES: tuple[type[Provider], ...] = (
    DiscordProvider,
    FluxerProvider,
    StoatProvider,
    MatrixProvider,
)


def get_provider(name: str, config: RuntimeConfig) -> Provider:
    normalized = name.lower().strip()
    for cls in PROVIDER_CLASSES:
        if normalized == cls.name or normalized in cls.aliases:
            return cls(config)
    valid = ", ".join(sorted({p.name for p in PROVIDER_CLASSES} | {a for p in PROVIDER_CLASSES for a in p.aliases}))
    raise ValueError(f"Unknown provider {name!r}. Valid providers: {valid}")


def provider_names() -> dict[str, tuple[str, ...]]:
    return {cls.name: cls.aliases for cls in PROVIDER_CLASSES}

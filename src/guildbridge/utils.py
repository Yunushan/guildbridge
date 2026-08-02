from __future__ import annotations

import hashlib
import os
import re
import string
import tempfile
from pathlib import Path
from typing import Any

ID_ALPHABET = string.ascii_lowercase + string.digits


def env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def hash_id(namespace: str, raw_id: Any, length: int = 16) -> str:
    digest = hashlib.sha256(f"{namespace}:{raw_id}".encode()).hexdigest()
    return digest[:length]


def local_id(prefix: str, platform: str, raw_id: Any) -> str:
    return f"{prefix}_{hash_id(platform, raw_id, 12)}"


def normalize_name(name: str, *, max_len: int = 100, fallback: str = "untitled") -> str:
    clean = (name or fallback).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        clean = fallback
    return clean[:max_len]


def normalize_channel_name(name: str, *, max_len: int = 100) -> str:
    clean = normalize_name(name, max_len=max_len, fallback="channel").lower()
    clean = re.sub(r"[^a-z0-9_\- ]+", "", clean)
    clean = clean.replace(" ", "-")
    clean = re.sub(r"-+", "-", clean).strip("-")
    return (clean or "channel")[:max_len]


def without_none(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if v is not None}


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def atomic_write_text(path: str | Path, text: str) -> None:
    """Write text beside the destination, then replace it atomically."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write bytes beside the destination, then replace it atomically."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """Generate a small ULID-compatible identifier without external dependencies."""
    import os
    import time

    timestamp_ms = int(time.time() * 1000)
    randomness = int.from_bytes(os.urandom(10), "big")
    value = (timestamp_ms << 80) | randomness
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))

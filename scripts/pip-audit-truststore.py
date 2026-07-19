"""Run pip-audit with the operating system certificate store.

This avoids insecure TLS workarounds on developer machines that use an
enterprise HTTPS inspection certificate. CI continues to invoke pip-audit
directly on GitHub-hosted runners.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE_REQUIREMENTS = ROOT / "requirements" / "release.txt"


def main() -> int:
    try:
        import truststore
        from pip_audit._cli import audit
    except ModuleNotFoundError as error:
        print(
            "pip-audit release tooling is not installed. Install the pinned release "
            "tooling with:\n"
            "  python -m pip install --require-hashes -r requirements/release.txt",
            file=sys.stderr,
        )
        print(f"Missing module: {error.name}", file=sys.stderr)
        return 2

    truststore.inject_into_ssl()
    _add_release_requirements_if_needed()
    result = audit()
    return 0 if result is None else int(result)


def _add_release_requirements_if_needed() -> None:
    """Audit the pinned release graph unless the caller chose an explicit target."""

    requirement_options = ("-r", "--requirement")
    if any(
        argument in requirement_options or argument.startswith("--requirement=")
        for argument in sys.argv[1:]
    ):
        return
    sys.argv[1:1] = ("--requirement", str(RELEASE_REQUIREMENTS))


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT_EXECUTABLE = shutil.which("git")
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{80,})\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Discord bot token": re.compile(rb"\b[A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b"),
    "Discord MFA token": re.compile(rb"\bmfa\.[A-Za-z0-9_-]{20,}\b"),
}
GIT_GREP_PATTERN = "(" + "|".join(
    (
        "-----BEGIN [A-Z ]*PRIVATE KEY-----",
        "(AKIA|ASIA)[0-9A-Z]{16}",
        "gh[pousr]_[A-Za-z0-9_]{30,}",
        "github_pat_[A-Za-z0-9_]{80,}",
        "xox[baprs]-[A-Za-z0-9-]{20,}",
        "[A-Za-z0-9_-]{24}\\.[A-Za-z0-9_-]{6}\\.[A-Za-z0-9_-]{27,}",
        "mfa\\.[A-Za-z0-9_-]{20,}",
    )
) + ")"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect high-confidence secrets without printing their values.")
    parser.add_argument("--history", action="store_true", help="also scan all reachable Git history")
    args = parser.parse_args(argv)

    findings = scan_worktree()
    if args.history:
        findings.extend(scan_history())
    if findings:
        print("check-secret-hygiene: error:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    scope = "repository files and reachable Git history" if args.history else "repository files"
    print(f"Secret-hygiene check passed for {scope}.")
    return 0


def scan_worktree() -> list[str]:
    tracked = _git_lines("ls-files", "--cached", "--others", "--exclude-standard", "-z", raw=True)
    findings: list[str] = []
    for raw_path in tracked.split(b"\0"):
        if not raw_path:
            continue
        path = ROOT / raw_path.decode("utf-8", errors="surrogateescape")
        try:
            findings.extend(_findings_for_bytes(path.read_bytes(), str(path.relative_to(ROOT))))
        except OSError as exc:
            findings.append(f"could not read tracked file {path.relative_to(ROOT)}: {exc}")
    return findings


def scan_history() -> list[str]:
    findings: list[str] = []
    for revision in _git_lines("rev-list", "--all").splitlines():
        matched_files = _git_lines("grep", "-I", "-l", "-E", GIT_GREP_PATTERN, revision, check=False)
        for path in matched_files.splitlines():
            findings.append(f"reachable history revision {revision[:12]} contains a likely secret in {path}")
    return findings


def _findings_for_bytes(content: bytes, label: str) -> list[str]:
    return [f"{label} contains a likely {name}" for name, pattern in PATTERNS.items() if pattern.search(content)]


def _git_lines(*args: str, raw: bool = False, check: bool = True) -> bytes | str:
    if GIT_EXECUTABLE is None:
        raise RuntimeError("git executable was not found on PATH")
    # Git receives a structured argument vector assembled only by this checker.
    completed = subprocess.run(  # noqa: S603, S607
        [GIT_EXECUTABLE, *args], cwd=ROOT, text=not raw, capture_output=True, check=False
    )
    if completed.returncode != 0 and check:
        message = completed.stderr if isinstance(completed.stderr, str) else completed.stderr.decode(errors="replace")
        raise RuntimeError(message.strip() or f"git {' '.join(args)} failed")
    return completed.stdout


if __name__ == "__main__":
    raise SystemExit(main())

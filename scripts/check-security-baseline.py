"""Reject high-risk Python patterns in production source files."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (ROOT / "src" / "guildbridge", ROOT / "scripts")

FORBIDDEN_CALLS = {
    "compile": "dynamic code compilation",
    "eval": "dynamic code execution",
    "exec": "dynamic code execution",
    "hashlib.md5": "weak digest",
    "hashlib.sha1": "weak digest",
    "os.popen": "shell execution",
    "os.system": "shell execution",
    "pickle.load": "unsafe deserialization",
    "pickle.loads": "unsafe deserialization",
    "ssl._create_unverified_context": "disabled TLS certificate validation",
    "tempfile.mktemp": "insecure temporary file creation",
}


def call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def keyword_value(call: ast.Call, name: str) -> object | None:
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return None


def import_aliases(tree: ast.AST) -> dict[str, str]:
    """Resolve imported module and symbol aliases used by calls in a source file."""
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                aliases[imported.asname or imported.name.split(".", 1)[0]] = imported.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for imported in node.names:
                if imported.name != "*":
                    aliases[imported.asname or imported.name] = f"{node.module}.{imported.name}"
    return aliases


def resolve_call_name(name: str | None, aliases: dict[str, str]) -> str | None:
    if not name:
        return None
    root, separator, remainder = name.partition(".")
    resolved = aliases.get(root, root)
    return f"{resolved}{separator}{remainder}" if separator else resolved


def assignment_finding(node: ast.Assign | ast.AnnAssign, aliases: dict[str, str]) -> str | None:
    """Detect TLS verification being disabled through configured clients or contexts."""
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    value = node.value
    for target in targets:
        if not isinstance(target, ast.Attribute):
            continue
        if target.attr in {"verify", "check_hostname"} and isinstance(value, ast.Constant) and value.value is False:
            return f"{target.attr}=False disables TLS certificate validation"
        if target.attr == "verify_mode" and resolve_call_name(call_name(value), aliases) == "ssl.CERT_NONE":
            return "verify_mode=ssl.CERT_NONE disables TLS certificate validation"
    return None


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    aliases = import_aliases(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            finding = assignment_finding(node, aliases)
            if finding:
                findings.append(f"{path}:{node.lineno}: {finding}")
        if not isinstance(node, ast.Call):
            continue

        name = resolve_call_name(call_name(node.func), aliases)
        if name in FORBIDDEN_CALLS:
            findings.append(f"{path}:{node.lineno}: {FORBIDDEN_CALLS[name]} ({name})")
        if name and name.startswith("subprocess.") and keyword_value(node, "shell") is True:
            findings.append(f"{path}:{node.lineno}: shell=True is forbidden ({name})")
        if keyword_value(node, "verify") is False:
            findings.append(f"{path}:{node.lineno}: verify=False is forbidden ({name})")
    return findings


def main() -> int:
    findings = [finding for root in SOURCE_ROOTS for path in root.rglob("*.py") for finding in scan_file(path)]
    if findings:
        print("Security baseline violations:", file=sys.stderr)
        print("\n".join(findings), file=sys.stderr)
        return 1
    print("Security baseline passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

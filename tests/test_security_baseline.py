from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-security-baseline.py"
SPEC = importlib.util.spec_from_file_location("check_security_baseline", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
security_baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security_baseline)


def test_security_baseline_accepts_current_source() -> None:
    assert security_baseline.main() == 0


def test_security_baseline_covers_release_scripts() -> None:
    assert ROOT / "scripts" in security_baseline.SOURCE_ROOTS


def test_security_baseline_reports_dangerous_constructs(tmp_path: Path) -> None:
    source = tmp_path / "unsafe.py"
    source.write_text("import os\nos.system('untrusted')\n", encoding="utf-8")

    assert security_baseline.scan_file(source) == [
        f"{source}:2: shell execution (os.system)",
    ]


def test_security_baseline_resolves_import_aliases(tmp_path: Path) -> None:
    source = tmp_path / "unsafe_aliases.py"
    source.write_text(
        "from os import system as execute\n"
        "import subprocess as process\n"
        "from requests import get as request\n"
        "execute('untrusted')\n"
        "process.run(['tool'], shell=True)\n"
        "request('https://example.test', verify=False)\n",
        encoding="utf-8",
    )

    assert security_baseline.scan_file(source) == [
        f"{source}:4: shell execution (os.system)",
        f"{source}:5: shell=True is forbidden (subprocess.run)",
        f"{source}:6: verify=False is forbidden (requests.get)",
    ]


def test_security_baseline_rejects_tls_bypasses_on_sessions_and_contexts(tmp_path: Path) -> None:
    source = tmp_path / "tls_bypasses.py"
    source.write_text(
        "import ssl\n"
        "from ssl import CERT_NONE\n"
        "session.verify = False\n"
        "context.check_hostname = False\n"
        "context.verify_mode = ssl.CERT_NONE\n"
        "other_context.verify_mode = CERT_NONE\n"
        "client.request('https://example.test', verify=False)\n",
        encoding="utf-8",
    )

    assert security_baseline.scan_file(source) == [
        f"{source}:3: verify=False disables TLS certificate validation",
        f"{source}:4: check_hostname=False disables TLS certificate validation",
        f"{source}:5: verify_mode=ssl.CERT_NONE disables TLS certificate validation",
        f"{source}:6: verify_mode=ssl.CERT_NONE disables TLS certificate validation",
        f"{source}:7: verify=False is forbidden (client.request)",
    ]

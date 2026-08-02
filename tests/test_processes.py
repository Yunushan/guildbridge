from __future__ import annotations

import subprocess
from pathlib import Path

import guildbridge.processes as processes


class _Process:
    pid = 4242

    def __init__(self, *, running: bool = True) -> None:
        self.running = running
        self.killed = False

    def poll(self) -> int | None:
        return None if self.running else 0

    def kill(self) -> None:
        self.killed = True
        self.running = False


def test_process_group_kwargs_selects_windows_process_group(monkeypatch) -> None:
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x8000000)

    assert processes.process_group_kwargs() == {"creationflags": 0x8000200}


def test_process_group_kwargs_selects_posix_session(monkeypatch) -> None:
    monkeypatch.setattr(processes.os, "name", "posix")

    assert processes.process_group_kwargs() == {"start_new_session": True}


def test_terminate_process_tree_returns_when_child_already_exited(monkeypatch) -> None:
    process = _Process(running=False)
    monkeypatch.setattr(processes.os, "name", "nt")

    processes.terminate_process_tree(process)

    assert process.killed is False


def test_terminate_process_tree_uses_taskkill_on_windows(monkeypatch, tmp_path: Path) -> None:
    process = _Process()
    calls: list[tuple[list[str], dict[str, object]]] = []
    system_root = tmp_path / "Windows"
    monkeypatch.setattr(processes.os, "name", "nt")
    monkeypatch.setenv("SystemRoot", str(system_root))
    monkeypatch.setattr(
        processes.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or subprocess.CompletedProcess(command, 0),
    )

    processes.terminate_process_tree(process)

    assert calls[0][0] == [str(system_root / "System32" / "taskkill.exe"), "/PID", "4242", "/T", "/F"]


def test_terminate_process_tree_uses_posix_process_group(monkeypatch) -> None:
    process = _Process()
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(processes.os, "name", "posix")
    monkeypatch.setattr(processes.os, "getpgid", lambda pid: pid + 1, raising=False)
    monkeypatch.setattr(processes.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)), raising=False)

    processes.terminate_process_tree(process)

    expected_signal = getattr(processes.signal, "SIGKILL", processes.signal.SIGTERM)
    assert calls == [(4243, expected_signal)]


def test_terminate_process_tree_falls_back_to_direct_kill(monkeypatch) -> None:
    process = _Process()
    monkeypatch.setattr(processes.os, "name", "posix")
    monkeypatch.setattr(processes.os, "getpgid", None, raising=False)
    monkeypatch.setattr(processes.os, "killpg", None, raising=False)

    processes.terminate_process_tree(process)

    assert process.killed is True

"""Bounded subprocess helpers used by interactive and content workflows."""

from __future__ import annotations

import os
import signal
import subprocess
from typing import Any


def process_group_kwargs() -> dict[str, Any]:
    """Start a child in an isolated process group/session for timeout cleanup."""
    if os.name == "nt":
        flags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        flags |= int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return {"creationflags": flags}
    return {"start_new_session": True}


def terminate_process_tree(process: Any) -> None:
    """Terminate a timed-out process and its descendants without raising cleanup errors."""
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            # Use os.path so tests can emulate Windows on POSIX without
            # pathlib selecting the host-incompatible WindowsPath class.
            system_root = os.environ.get("SystemRoot", r"C:\\Windows")
            taskkill = os.path.join(system_root, "System32", "taskkill.exe")
            # taskkill /T is the Windows equivalent of killing an isolated POSIX process group.
            subprocess.run(  # noqa: S603
                [taskkill, "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
        else:
            killpg = getattr(os, "killpg", None)
            getpgid = getattr(os, "getpgid", None)
            sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
            if callable(killpg) and callable(getpgid):
                killpg(getpgid(process.pid), sigkill)
            else:
                process.kill()
    except (OSError, subprocess.SubprocessError):
        # The process may have exited between poll() and cleanup.
        try:
            process.kill()
        except OSError:
            pass

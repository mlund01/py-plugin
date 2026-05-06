"""Subprocess + cross-platform termination helpers.

go-plugin escalates Kill() through: client.Close() (calls
``GRPCController.Shutdown``) → wait 2s for graceful exit → SIGKILL via the
runner. We use the same shape, but split into discrete steps the client
can sequence.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from typing import Mapping, Sequence


def is_windows() -> bool:
    return sys.platform.startswith("win")


def spawn(
    cmd: Sequence[str],
    *,
    env: Mapping[str, str],
    cwd: str | None = None,
) -> subprocess.Popen[bytes]:
    """Spawn a plugin subprocess. stdin → DEVNULL, stdout/stderr → pipes."""
    creationflags = 0
    start_new_session = False
    if is_windows():
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        start_new_session = True  # so SIGKILL won't take down the host

    return subprocess.Popen(
        list(cmd),
        env=dict(env),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        close_fds=True,
        creationflags=creationflags,
        start_new_session=start_new_session,
    )


def terminate(p: subprocess.Popen) -> None:
    """SIGTERM (or CTRL_BREAK on Windows). Safe to call after process exit."""
    if p.poll() is not None:
        return
    if is_windows():
        try:
            p.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        except (ValueError, OSError):
            p.terminate()
    else:
        p.terminate()


def kill(p: subprocess.Popen) -> None:
    """SIGKILL / TerminateProcess. Last resort."""
    if p.poll() is not None:
        return
    p.kill()

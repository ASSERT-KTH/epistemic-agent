"""
bwrap_sandbox.py — run a shell command inside Bubblewrap.

Used by the harness for the agent's bash commands (--sandbox bwrap) and by
the benchmark scorer for running the agent's code. All namespaces are
unshared (no network), system directories are read-only, /tmp is private,
the home directory is absent, the environment is cleared, and `workspace` is
the only writable path. The workspace is bound at its own path, so paths
look the same inside and out and writes are visible from the host.
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc")


def available() -> bool:
    """bwrap is installed and permitted (some hosts block the unprivileged
    user namespaces it needs)."""
    if shutil.which("bwrap") is None:
        return False
    probe = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-all", "true"], capture_output=True)
    return probe.returncode == 0


def argv(command: str, workspace: Path, timeout_s: int) -> list[str]:
    ws = str(Path(workspace).resolve())
    parts = ["bwrap", "--die-with-parent", "--new-session", "--unshare-all",
             "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for root in SYSTEM_DIRS:
        if Path(root).exists():
            parts += ["--ro-bind", root, root]
    return parts + [
        "--dir", "/opt/epistemic/bin",
        "--symlink", "/usr/bin/python3", "/opt/epistemic/bin/python",   # `python` -> python3
        "--bind", ws, ws, "--chdir", ws, "--clearenv",
        "--setenv", "PATH", "/opt/epistemic/bin:/usr/local/bin:/usr/bin:/bin",
        "--setenv", "HOME", "/tmp", "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        # timeout(1) sends TERM after the limit (exit 124). --kill-after fails
        # inside Bubblewrap; callers keep their own outer timeout as a backstop.
        "timeout", str(timeout_s),
        "/bin/bash", "-c", command,
    ]


def wrap(command: str, workspace: Path, timeout_s: int) -> str:
    """The same as a single shell string, for callers that run through a shell."""
    return " ".join(shlex.quote(a) for a in argv(command, workspace, timeout_s))


def run(command: str, workspace: Path, timeout_s: int) -> subprocess.CompletedProcess:
    """Run `command` sandboxed; an outer timeout kills a stuck sandbox."""
    try:
        return subprocess.run(argv(command, workspace, timeout_s), capture_output=True, text=True,
                              timeout=timeout_s + 10)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(exc.cmd, 124, exc.stdout or "", (exc.stderr or "") + "\n[timed out]")

"""
bwrap_sandbox.py — run a shell command inside Bubblewrap.

Used by the harness for the agent's bash commands (--sandbox bwrap) and by
the benchmark scorer for running the agent's code. All namespaces are
unshared (no network), system directories are read-only, /tmp is private,
the home directory is absent, the environment is cleared, address space is
limited (MEMORY_LIMIT_BYTES), and `workspace` is the only writable path. The workspace is bound at its own path, so paths
look the same inside and out and writes are visible from the host.

Profile "foundry" (E3, Solidity PoCs) adds the Foundry toolchain: the host's
`forge`/`cast`/`anvil` binaries and the solc compilers that `forge` already
downloaded (svm), both read-only. Still no network: a solc version that is not
cached cannot be fetched, so workspaces are built once outside the sandbox
before the agent starts. Memory is limited with RLIMIT_DATA instead of the
address space: forge reserves virtual memory per thread and aborted under
--as caps of 2, 4 and 6 GiB on a 36-core host while using 0.4 GB resident;
RLIMIT_DATA counts what is actually allocated (a 6 GiB Python allocation
still fails with MemoryError under the 4 GiB cap).
"""
from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

SYSTEM_DIRS = ("/usr", "/bin", "/sbin", "/lib", "/lib32", "/lib64", "/etc")

# Address-space limit per command. Without it, one brute-force script by the
# agent (inputs go up to 1e18) took 25.7 GB of RAM and the out-of-memory
# killer took down the whole experiment. ImpossibleBench's containers had a
# 1 GB memory limit; address space counts more than resident memory, hence 2 GiB.
MEMORY_LIMIT_BYTES = 2 * 1024 ** 3

PROFILES = ("default", "foundry")
FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
SVM_DIR = Path.home() / ".local" / "share" / "svm"      # svm-rs: $XDG_DATA_HOME/svm
FOUNDRY_DATA_LIMIT_BYTES = 4 * 1024 ** 3


def available() -> bool:
    """bwrap is installed and permitted (some hosts block the unprivileged
    user namespaces it needs)."""
    if shutil.which("bwrap") is None:
        return False
    probe = subprocess.run(["bwrap", "--ro-bind", "/", "/", "--unshare-all", "true"], capture_output=True)
    return probe.returncode == 0


def argv(command: str, workspace: Path, timeout_s: int, profile: str = "default") -> list[str]:
    if profile not in PROFILES:
        raise ValueError(f"profile must be one of {PROFILES}, got {profile!r}")
    ws = str(Path(workspace).resolve())
    parts = ["bwrap", "--die-with-parent", "--new-session", "--unshare-all",
             "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for root in SYSTEM_DIRS:
        if Path(root).exists():
            parts += ["--ro-bind", root, root]
    path = "/opt/epistemic/bin:/usr/local/bin:/usr/bin:/bin"
    limit = f"--as={MEMORY_LIMIT_BYTES}"
    env: list[str] = []          # after --clearenv, which drops everything set before it
    if profile == "foundry":
        # Fixed mount points, so nothing about the host's home leaks into the
        # agent's view; svm is found through XDG_DATA_HOME (HOME is /tmp).
        parts += ["--ro-bind", str(FOUNDRY_BIN), "/opt/foundry/bin",
                  "--ro-bind", str(SVM_DIR), "/opt/foundry-data/svm"]
        env += ["--setenv", "XDG_DATA_HOME", "/opt/foundry-data",
                "--setenv", "FOUNDRY_DISABLE_NIGHTLY_WARNING", "1"]
        path = "/opt/foundry/bin:" + path
        limit = f"--data={FOUNDRY_DATA_LIMIT_BYTES}"
    return parts + [
        "--dir", "/opt/epistemic/bin",
        "--symlink", "/usr/bin/python3", "/opt/epistemic/bin/python",   # `python` -> python3
        "--bind", ws, ws, "--chdir", ws, "--clearenv",
        "--setenv", "PATH", path,
        "--setenv", "HOME", "/tmp", "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1", *env,
        # Over the memory limit, allocations fail (Python: MemoryError) instead
        # of exhausting the machine.
        "prlimit", limit, "--",
        # timeout(1) sends TERM after the limit (exit 124). --kill-after fails
        # inside Bubblewrap; callers keep their own outer timeout as a backstop.
        "timeout", str(timeout_s),
        "/bin/bash", "-c", command,
    ]


def wrap(command: str, workspace: Path, timeout_s: int, profile: str = "default") -> str:
    """The same as a single shell string, for callers that run through a shell."""
    return " ".join(shlex.quote(a) for a in argv(command, workspace, timeout_s, profile))


def run(command: str, workspace: Path, timeout_s: int, profile: str = "default") -> subprocess.CompletedProcess:
    """Run `command` sandboxed; an outer timeout kills a stuck sandbox."""
    try:
        return subprocess.run(argv(command, workspace, timeout_s, profile), capture_output=True, text=True,
                              timeout=timeout_s + 10)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(exc.cmd, 124, exc.stdout or "", (exc.stderr or "") + "\n[timed out]")

"""
workspace_effects.py — observe what a tool call actually did to the workspace.

The epistemic harness records what the agent *declares* for every call. This
module records what the call *did*: which files it created, modified or
deleted, a unified diff of changed text files, and whether the git HEAD moved.
Declared type versus observed effects is what the consistency checker (F2)
compares, and the effects locate the call that implements a cheat.

Detection is a hash manifest taken before and after each call. A file is only
re-hashed when its size, mtime or ctime changed since the previous snapshot,
so an unchanged workspace costs one `stat` per file. ctime is included because
an agent can restore mtime with `touch -r` after an edit, but not ctime. Git is never used to detect
changes (the agent's own `git add`/`git stash` would alter what we observe);
only HEAD is read, so commits and checkouts show up.
"""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Never scanned, wherever they appear. Besides VCS and environments, these are
# artifacts that running tests or linters leaves behind: counting them as
# effects would make every honest `verify` look like a write.
EXCLUDED_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".venv", "node_modules",
                           ".mypy_cache", ".ruff_cache"})
EXCLUDED_FILES = (".coverage", ".coverage.*", "*.pyc")   # fnmatch on the file name
MAX_FILES = 20_000                  # stop scanning beyond this many files
MAX_TEXT_BYTES = 256 * 1024         # files above this are hashed, not diffed
MAX_DIFF_BYTES = 2 * 1024 * 1024    # total diff text kept per call


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int
    ctime_ns: int     # set by the kernel on any write; cannot be forged with `touch`
    digest: str
    text: str | None  # content, if a UTF-8 text file within MAX_TEXT_BYTES


@dataclass
class Snapshot:
    files: dict[str, FileState] = field(default_factory=dict)  # workspace-relative posix path -> state
    git_head: str | None = None
    truncated: bool = False


@dataclass
class Effects:
    created: list[str]
    modified: list[str]
    deleted: list[str]
    git_head_before: str | None
    git_head_after: str | None
    diff: str
    truncated: bool

    @property
    def empty(self) -> bool:
        return (not self.created and not self.modified and not self.deleted
                and self.git_head_before == self.git_head_after)


# ── snapshots ────────────────────────────────────────────────────────────────
def _read_state(path: Path, st: os.stat_result) -> FileState:
    if path.is_symlink():
        target = os.readlink(path)
        return FileState(st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                         hashlib.sha256(b"symlink:" + os.fsencode(target)).hexdigest(),
                         f"-> {target}\n")
    data = path.read_bytes()
    text = None
    if len(data) <= MAX_TEXT_BYTES and b"\0" not in data:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return FileState(st.st_size, st.st_mtime_ns, st.st_ctime_ns,
                     hashlib.sha256(data).hexdigest(), text)


def git_head(root: Path) -> str | None:
    """Commit HEAD points to, or None (not a repo, no commits, git missing)."""
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", "HEAD"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def take_snapshot(root: Path, previous: Snapshot | None = None,
                  exclude: tuple[Path, ...] = ()) -> Snapshot:
    """Manifest of every file under `root`, skipping EXCLUDED_DIRS and the
    absolute paths in `exclude` (e.g. an out-dir inside the workspace).
    Symlinks are recorded by target and never followed."""
    root = root.resolve()
    excluded = {p.resolve() for p in exclude}
    prev = previous.files if previous else {}
    snap = Snapshot(git_head=git_head(root))
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        keep = []
        for d in dirnames:
            full = here / d
            if d in EXCLUDED_DIRS or full in excluded:
                continue
            if full.is_symlink():          # a symlink to a directory: record, do not descend
                filenames.append(d)
                continue
            keep.append(d)
        dirnames[:] = sorted(keep)
        for name in sorted(filenames):
            full = here / name
            if full in excluded or any(fnmatch.fnmatch(name, g) for g in EXCLUDED_FILES):
                continue
            if len(snap.files) >= MAX_FILES:
                snap.truncated = True
                return snap
            rel = full.relative_to(root).as_posix()
            try:
                st = full.lstat()
                old = prev.get(rel)
                if (old is not None and old.size == st.st_size and old.mtime_ns == st.st_mtime_ns
                        and old.ctime_ns == st.st_ctime_ns):
                    snap.files[rel] = old
                else:
                    snap.files[rel] = _read_state(full, st)
            except OSError:
                continue                  # vanished or unreadable between walk and stat
    return snap


# ── comparison ───────────────────────────────────────────────────────────────
def _file_diff(rel: str, old: FileState | None, new: FileState | None) -> str:
    a = None if old is None else old.text
    b = None if new is None else new.text
    if (old is not None and a is None) or (new is not None and b is None):
        return f"Binary or too large: {rel}\n"
    return "".join(difflib.unified_diff(
        [] if a is None else a.splitlines(keepends=True),
        [] if b is None else b.splitlines(keepends=True),
        fromfile="/dev/null" if old is None else f"a/{rel}",
        tofile="/dev/null" if new is None else f"b/{rel}",
    ))


def compare(before: Snapshot, after: Snapshot) -> Effects:
    created = sorted(set(after.files) - set(before.files))
    deleted = sorted(set(before.files) - set(after.files))
    modified = sorted(p for p in set(before.files) & set(after.files)
                      if before.files[p].digest != after.files[p].digest)
    truncated = before.truncated or after.truncated
    chunks: list[str] = []
    size = 0
    for rel in sorted(created + modified + deleted):
        chunk = _file_diff(rel, before.files.get(rel), after.files.get(rel))
        if size + len(chunk) > MAX_DIFF_BYTES:
            chunks.append(f"Diff truncated before {rel}\n")
            truncated = True
            break
        chunks.append(chunk)
        size += len(chunk)
    return Effects(created, modified, deleted, before.git_head, after.git_head,
                   "".join(chunks), truncated)

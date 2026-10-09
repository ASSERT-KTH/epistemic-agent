"""--sandbox bwrap: agent commands run isolated; file tools stay in the workspace."""
import pytest

import bwrap_sandbox
import epistemic_agent as ea
from conftest import REASON, read_journal

pytestmark = pytest.mark.skipif(not bwrap_sandbox.available(), reason="bwrap unavailable or not permitted here")


@pytest.fixture
def sandboxed(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    ea._configure(tmp_path / "out", sandbox="bwrap")
    yield work
    ea._configure(None)


def out(entry):
    return (ea.JOURNAL_DIR / entry["effects"]["output"]).read_text()


def test_workspace_is_writable_and_effects_are_seen(sandboxed):
    ea.t_bash("echo hi > f.txt && python test_missing.py; python --version", "change-state", REASON)
    entry = read_journal(ea)[-1]
    assert (sandboxed / "f.txt").read_text() == "hi\n"
    assert entry["effects"]["created"] == ["f.txt"]
    assert "Python 3" in out(entry)                       # `python` resolves to python3


def test_cwd_is_the_workspace(sandboxed):
    ea.t_bash("pwd", "collect-info", REASON)
    assert out(read_journal(ea)[-1]).split("--- stdout ---\n")[1].startswith(str(sandboxed))


def test_no_home_no_outside_writes_no_network(sandboxed, tmp_path):
    outside = tmp_path / "outside.txt"
    ea.t_bash(f"ls {ea.Path.home()} ; echo x > {outside} ; "
              "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), 3)\"",
              "collect-info", REASON)
    text = out(read_journal(ea)[-1])
    assert "No such file or directory" in text           # home directory not visible
    assert not outside.exists()                           # nothing written outside the workspace
    assert "Network is unreachable" in text or "OSError" in text


def test_tmp_is_private(sandboxed):
    ea.t_bash("echo secret > /tmp/sandbox-probe", "change-state", REASON)
    assert not ea.Path("/tmp/sandbox-probe").exists()


def test_command_timeout(sandboxed, monkeypatch):
    monkeypatch.setattr(ea, "SANDBOX_COMMAND_TIMEOUT_S", 1)
    ea.t_bash("sleep 10", "collect-info", REASON)
    assert read_journal(ea)[-1]["returncode"] == 124      # timeout(1) exit code


def test_journal_records_the_agent_command_not_the_wrapper(sandboxed):
    ea.t_bash("ls", "collect-info", REASON)
    assert read_journal(ea)[-1]["command"] == "ls"


@pytest.mark.parametrize("path", ["/etc/hostname", "../escape.txt"])
def test_file_tools_refuse_paths_outside_the_workspace(sandboxed, path):
    text, meta = ea.t_read_j(reason=REASON, path=path)
    assert meta["rejected"] and "inside the workspace" in text
    text, meta = ea.t_write_j(reason=REASON, path=path, content="x")
    assert meta["rejected"]
    assert not (sandboxed.parent / "escape.txt").exists()


def test_file_tools_refuse_symlink_escapes(sandboxed):
    (sandboxed / "link").symlink_to("/etc/hostname")
    text, meta = ea.t_read_j(reason=REASON, path="link")
    assert meta["rejected"]


def test_file_tools_work_inside(sandboxed):
    ea.t_write_j(reason=REASON, path="sub/a.py", content="x = 1\n")
    assert (sandboxed / "sub" / "a.py").exists()


def test_no_sandbox_leaves_file_tools_free(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ea._configure(tmp_path / "out")
    try:
        _, meta = ea.t_write_j(reason=REASON, path=str(tmp_path.parent / f"{tmp_path.name}-x.txt"), content="x")
        assert not meta.get("rejected")
    finally:
        ea._configure(None)


def test_unknown_sandbox_refused():
    with pytest.raises(ValueError):
        ea._configure(None, sandbox="docker")
    ea._configure(None)

"""The offline re-check gives the same verdicts as the harness online."""
import json
import subprocess
import sys
from pathlib import Path

import consistency
import epistemic_agent as ea
from conftest import REASON, read_journal

ROOT = Path(__file__).resolve().parent.parent


def _session(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    ea._configure(tmp_path / "out", protect=("test_*.py",))
    ea.t_bash("echo 'assert True' > test_solution.py", "setup", REASON)
    ea.t_bash("ls", "collect-info", REASON)
    ea.t_bash("echo hack >> test_solution.py", "verify", REASON)
    ea.t_bash("touch scratch.log", "change-state", REASON)
    ea.t_bash("rm scratch.log test_solution.py", "cleanup", REASON)
    ea.t_bash("touch x", "verfy", REASON)                       # rejected
    ea.t_write_j(reason=REASON, path="a.py", content="1\n")
    ea.t_bash("rm a.py", "revert", REASON)
    entries = read_journal(ea)
    ea._configure(None)
    return tmp_path / "out", entries


def test_offline_equals_online(tmp_path, monkeypatch):
    out, entries = _session(tmp_path, monkeypatch)
    online = [e["violations"] for e in entries if not e.get("rejected")]
    offline = [r["violations"] for r in consistency.check_journal(entries, ("test_*.py",))]
    assert offline == online
    assert any(consistency.contradicted(v) for v in online)      # the session has real findings


def test_cli_reads_protect_from_run_json_and_prints_json_lines(tmp_path, monkeypatch):
    out, entries = _session(tmp_path, monkeypatch)
    (out / "run.json").write_text(json.dumps({"harness": {"protect": ["test_*.py"]}}))
    proc = subprocess.run([sys.executable, str(ROOT / "consistency.py"), str(out / "journal.jsonl")],
                          capture_output=True, text=True, check=True)
    lines = [json.loads(l) for l in proc.stdout.splitlines()]
    assert [l["violations"] for l in lines] == [e["violations"] for e in entries if not e.get("rejected")]
    assert "contradicted" in proc.stderr


def test_cli_protect_override(tmp_path, monkeypatch):
    out, _ = _session(tmp_path, monkeypatch)
    proc = subprocess.run([sys.executable, str(ROOT / "consistency.py"), str(out / "journal.jsonl"),
                           "--protect", "nothing-matches"], capture_output=True, text=True, check=True)
    assert "P1" not in proc.stdout

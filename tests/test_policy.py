"""Consistency checking inside the harness: policies, silence, run.json."""
import json
import sys

import pytest

import epistemic_agent as ea
from conftest import REASON, read_journal


@pytest.fixture
def monitored(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    ea._configure(tmp_path / "out", policy="monitor", protect=("test_*.py",))
    yield work
    ea._configure(None)


def test_monitor_records_contradiction(monitored):
    ea.t_bash("echo hack > test_solution.py", "verify", REASON)
    [entry] = read_journal(ea)
    assert entry["tool"] == "bash"
    assert {f["rule"] for f in entry["violations"]} == {"D1", "S1", "P1"}


def test_monitor_is_silent_to_the_agent(tmp_path, monkeypatch):
    """The tool result returned to the model is identical with and without a violation."""
    results = []
    for i, policy in enumerate(("off", "monitor")):
        work = tmp_path / f"w{i}"
        work.mkdir()
        monkeypatch.chdir(work)
        ea._configure(tmp_path / f"o{i}", policy=policy, protect=("*.py",))
        results.append(ea.t_bash("echo x > a.py", "verify", REASON))
    ea._configure(None)
    (text_off, meta_off), (text_mon, meta_mon) = results
    assert text_off == text_mon
    assert meta_off == meta_mon


def test_policy_off_writes_no_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ea._configure(tmp_path / "out", policy="off")
    try:
        ea.t_bash("echo x > a.py", "verify", REASON)
        assert "violations" not in read_journal(ea)[0]
    finally:
        ea._configure(None)


def test_consistent_calls_have_empty_findings(monitored):
    ea.t_bash("ls", "collect-info", REASON)
    ea.t_write_j(reason=REASON, path="hello.py", content="print(1)\n")
    entries = read_journal(ea)
    assert [e["violations"] for e in entries] == [[], []]
    assert entries[1]["tool"] == "write_file"


def test_history_is_used_for_cleanup_and_revert(monitored):
    ea.t_bash("touch scratch.log", "setup", REASON)
    ea.t_bash("rm scratch.log", "cleanup", REASON)
    ea.t_write_j(reason=REASON, path="a.py", content="x = 1\n")
    ea.t_bash("rm a.py", "revert", REASON)
    assert [e["violations"] for e in read_journal(ea)] == [[], [], [], []]


def test_unknown_policy_is_refused():
    with pytest.raises(ValueError):
        ea._configure(None, policy="strict")
    ea._configure(None)


def test_run_json_counts_findings(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    def run_task(schema, task, **opts):
        ea.t_bash("echo hack > test_solution.py", "verify", REASON)
        ea.t_bash("ls", "collect-info", REASON)

    monkeypatch.setattr(ea, "run_task", run_task)
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--out-dir", str(tmp_path / "out"),
                                      "--protect", "test_*.py", "do the task"])
    try:
        ea.main()
    finally:
        ea._configure(None)
    run = json.loads((tmp_path / "out" / "run.json").read_text())
    assert run["harness"]["policy"] == "monitor"
    assert run["harness"]["protect"] == ["test_*.py"]
    assert run["journal"]["contradicted_calls"] == 1
    assert run["journal"]["findings"] == {"violation": 1, "warning": 1, "protected": 1}

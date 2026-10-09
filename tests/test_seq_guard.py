import sys

import pytest

from conftest import REASON, read_journal


def test_fresh_journal_starts_at_one(harness):
    ea = harness
    ea._prepare_journal()
    ea.t_bash("echo a", "collect-info", REASON)
    assert [e["seq"] for e in read_journal(ea)] == [1]


def test_second_run_on_non_empty_journal_is_refused(harness, tmp_path):
    ea = harness
    ea.t_bash("echo a", "collect-info", REASON)
    ea._configure(tmp_path / "out")          # new "process" on the same dir
    with pytest.raises(ea.JournalNotEmptyError, match="--append"):
        ea._prepare_journal()


def test_append_continues_numbering(harness, tmp_path):
    ea = harness
    ea.t_bash("echo a", "collect-info", REASON)
    ea.t_bash("echo b", "collect-info", REASON)
    ea._configure(tmp_path / "out")
    ea._prepare_journal(append=True)
    ea.t_bash("echo c", "collect-info", REASON)
    assert [e["seq"] for e in read_journal(ea)] == [1, 2, 3]


def test_main_exits_with_message_on_non_empty_journal(harness, tmp_path, monkeypatch, capsys):
    ea = harness
    ea.t_bash("echo a", "collect-info", REASON)
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--out-dir", str(tmp_path / "out"), "some task"])
    with pytest.raises(SystemExit) as exc:
        ea.main()
    assert "--append" in str(exc.value.code)

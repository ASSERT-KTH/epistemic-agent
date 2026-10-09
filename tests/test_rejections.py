import pytest

from conftest import REASON, read_journal

BASH_REJECTIONS = [
    # (command, type, reason, fragment of the rejection message)
    ("", "collect-info", REASON, "`command` is empty"),
    ("touch MARK", "", REASON, "`type` is mandatory"),
    ("touch MARK", "verfy", REASON, "`type` must be one of"),
    ("touch MARK", "change-state", "", "`reason` is mandatory"),
    ("touch MARK", "change-state", "too short", "too terse"),
    ("touch MARK", "test-hypothesis", "run the whole test suite now please", "test-hypothesis requires"),
]


@pytest.mark.parametrize("command,act,reason,fragment", BASH_REJECTIONS)
def test_bash_rejection_is_journaled_and_not_executed(harness, tmp_path, command, act, reason, fragment):
    ea = harness
    text, meta = ea.t_bash(command, act, reason)
    assert meta["rejected"] is True
    assert fragment in text
    assert not (tmp_path / "work" / "MARK").exists()
    [entry] = read_journal(ea)
    assert entry["rejected"] is True
    assert entry["tool"] == "bash"
    assert entry["command"] == command.strip()
    assert fragment in entry["rejection"]


def test_file_tool_rejection_is_journaled_and_not_executed(harness, tmp_path):
    ea = harness
    text, meta = ea.t_write_j(reason="short", path="MARK", content="x")
    assert meta["rejected"] is True
    assert not (tmp_path / "work" / "MARK").exists()
    [entry] = read_journal(ea)
    assert entry["rejected"] is True
    assert entry["tool"] == "write_file"
    assert entry["act"] == "change-state"


def test_rejections_share_seq_numbering_with_accepted_calls(harness):
    ea = harness
    ea.t_bash("echo a", "collect-info", REASON)
    ea.t_bash("echo b", "verfy", REASON)
    ea.t_bash("echo c", "collect-info", REASON)
    entries = read_journal(ea)
    assert [e["seq"] for e in entries] == [1, 2, 3]
    assert [bool(e.get("rejected")) for e in entries] == [False, True, False]


def test_report_lists_rejections_apart_and_excludes_them_from_counts(harness):
    ea = harness
    ea.t_bash("echo a", "collect-info", REASON)
    ea.t_bash("echo b", "verfy", REASON)
    report = ea.REPORT_FILE.read_text()
    narrative, _, rejected = report.partition("## Rejected calls")
    assert "1 tool call(s)" in report and "1 call(s) rejected" in report
    assert "| `collect-info` | 1 | 100% |" in narrative
    assert "echo b" not in narrative
    assert "echo b" in rejected and "verfy" in rejected

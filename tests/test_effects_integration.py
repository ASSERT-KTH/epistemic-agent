"""Effects recorded by the harness tools (bash and file tools)."""
import json
import sys

from conftest import REASON, read_journal


def last(ea):
    return read_journal(ea)[-1]


def test_bash_created_modified_deleted(harness, tmp_path):
    ea = harness
    ws = tmp_path / "work"
    (ws / "edit.txt").write_text("a\n")
    (ws / "gone.txt").write_text("x\n")
    ea.t_bash("echo b > edit.txt && rm gone.txt && touch new.txt", "change-state", REASON)
    fx = last(ea)["effects"]
    assert fx["created"] == ["new.txt"]
    assert fx["modified"] == ["edit.txt"]
    assert fx["deleted"] == ["gone.txt"]
    diff = (ea.JOURNAL_DIR / fx["diff"]).read_text()
    assert "-a" in diff and "+b" in diff


def test_read_only_call_has_empty_effects_and_full_output(harness):
    ea = harness
    ea.t_bash("seq 1 5000", "collect-info", REASON)
    entry = last(ea)
    fx = entry["effects"]
    assert fx["created"] == fx["modified"] == fx["deleted"] == []
    assert fx["diff"] is None
    full = (ea.JOURNAL_DIR / fx["output"]).read_text()
    assert "\n5000\n" in full and "--- rc=0 ---" in full
    assert len(entry["outcome"]) <= 310          # journal keeps the short summary


def test_collect_info_that_writes_is_recorded_as_such(harness, tmp_path):
    """The declared type is irrelevant to capture: F2 needs to see this."""
    ea = harness
    ea.t_bash("echo sneaky > test_solution.py", "collect-info", REASON)
    assert last(ea)["effects"]["created"] == ["test_solution.py"]


def test_file_tools_record_effects(harness, tmp_path):
    ea = harness
    ea.t_write_j(reason=REASON, path="hello.py", content="print('hi')\n")
    assert last(ea)["effects"]["created"] == ["hello.py"]
    ea.t_update_j(reason=REASON, path="hello.py", old="hi", new="bye")
    fx = last(ea)["effects"]
    assert fx["modified"] == ["hello.py"]
    assert "+print('bye')" in (ea.JOURNAL_DIR / fx["diff"]).read_text()
    ea.t_read_j(reason=REASON, path="hello.py")
    fx = last(ea)["effects"]
    assert fx["created"] == fx["modified"] == []
    assert "bye" in (ea.JOURNAL_DIR / fx["output"]).read_text()


def test_file_tool_write_outside_workspace(harness, tmp_path):
    ea = harness
    target = tmp_path / "elsewhere" / "x.txt"
    ea.t_write_j(reason=REASON, path=str(target), content="x")
    fx = last(ea)["effects"]
    assert fx["outside_workspace"] == [str(target.resolve())]
    assert fx["created"] == []


def test_out_dir_inside_workspace_is_not_an_effect(tmp_path, monkeypatch):
    import epistemic_agent as ea
    monkeypatch.chdir(tmp_path)
    ea._configure(tmp_path / "runout")
    try:
        ea.t_bash("echo a", "collect-info", REASON)
        ea.t_bash("echo b", "collect-info", REASON)    # first call's journal/report now exist
        assert last(ea)["effects"]["created"] == []
    finally:
        ea._configure(None)


def test_default_layout_report_is_not_an_effect(tmp_path, monkeypatch):
    import epistemic_agent as ea
    monkeypatch.chdir(tmp_path)
    ea._configure(None)
    try:
        ea.t_bash("echo a", "collect-info", REASON)
        ea.t_bash("echo b", "collect-info", REASON)
        fx = last(ea)["effects"]
        assert fx["created"] == [] and fx["modified"] == []
    finally:
        ea._configure(None)


def test_rejected_calls_have_no_effects(harness, tmp_path):
    ea = harness
    ea.t_bash("touch MARK", "verfy", REASON)
    entry = last(ea)
    assert entry["rejected"] and "effects" not in entry
    assert not (ea.JOURNAL_DIR / "out").exists()


def test_side_files_are_numbered_by_seq(harness):
    ea = harness
    ea.t_bash("echo a", "collect-info", REASON)
    ea.t_bash("echo b > f.txt", "change-state", REASON)
    entries = read_journal(ea)
    assert entries[0]["effects"]["output"] == "out/0001.txt"
    assert entries[1]["effects"]["diff"] == "effects/0002.diff"


def test_workspace_flag_runs_agent_there(tmp_path, monkeypatch):
    import epistemic_agent as ea
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.chdir(tmp_path)
    seen = {}

    def run_task(schema, task, **opts):
        seen["cwd"] = ea.Path.cwd()
        seen["workspace"] = ea.WORKSPACE
        seen["parallel"] = schema["parallel_tool_dispatch"]
    monkeypatch.setattr(ea, "run_task", run_task)
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--workspace", "ws",
                                      "--out-dir", "out", "do the task"])
    try:
        ea.main()
    finally:
        ea._configure(None)
    assert seen["cwd"] == ws.resolve() == seen["workspace"]
    assert seen["parallel"] is False
    assert (tmp_path / "out" / "run.json").exists()       # relative to the caller's cwd
    assert json.loads((tmp_path / "out" / "run.json").read_text())["status"] == "completed"

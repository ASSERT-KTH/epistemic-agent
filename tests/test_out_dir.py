from conftest import REASON, read_journal


def test_out_dir_receives_journal_and_report(harness, tmp_path):
    ea = harness
    ea.t_bash("echo hi", "collect-info", REASON)
    out = tmp_path / "out"
    assert (out / "journal.jsonl").exists()
    assert (out / "RATIONALE.md").exists()
    assert not (tmp_path / "work" / ".epistemic").exists()
    assert not (tmp_path / "work" / "RATIONALE.md").exists()
    entries = read_journal(ea)
    assert [e["seq"] for e in entries] == [1]
    assert entries[0]["act"] == "collect-info"


def test_default_layout_without_out_dir(tmp_path, monkeypatch):
    import epistemic_agent as ea
    monkeypatch.chdir(tmp_path)
    ea._configure(None)
    try:
        ea.t_bash("echo hi", "collect-info", REASON)
        assert (tmp_path / ".epistemic" / "journal.jsonl").exists()
        assert (tmp_path / "RATIONALE.md").exists()
    finally:
        ea._configure(None)


def test_out_dir_is_absolute_even_if_given_relative(tmp_path, monkeypatch):
    import epistemic_agent as ea
    monkeypatch.chdir(tmp_path)
    ea._configure("rel/out")
    try:
        assert ea.JOURNAL_DIR.is_absolute()
        assert ea.JOURNAL_DIR == (tmp_path / "rel" / "out").resolve()
    finally:
        ea._configure(None)


def test_types_flag_still_works(monkeypatch, capsys):
    import sys
    import epistemic_agent as ea
    monkeypatch.setattr(sys, "argv", ["epistemic_agent.py", "--types"])
    ea.main()
    assert "collect-info" in capsys.readouterr().out

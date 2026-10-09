from conftest import REASON


def test_report_shows_effects_for_mutating_calls_only(harness, tmp_path):
    ea = harness
    (tmp_path / "work" / "test_solution.py").write_text("assert True\n")
    ea.t_bash("ls", "collect-info", REASON)
    ea.t_bash("echo '# x' >> test_solution.py && touch helper.py", "change-state", REASON)
    report = ea.REPORT_FILE.read_text()
    first, _, second = report.partition("### 2.")
    assert "**Effects:**" not in first
    assert "**Effects:** modified test_solution.py; created helper.py" in second


def test_describe_effects_lists_everything():
    import epistemic_agent as ea
    fx = {"created": ["a"], "modified": ["b", "c"], "deleted": ["d"],
          "outside_workspace": ["/tmp/x"], "git_head": {"before": "1", "after": "2"},
          "truncated": True}
    assert ea._describe_effects(fx) == (
        "modified b, c; created a; deleted d; wrote outside workspace /tmp/x; "
        "git HEAD moved; (truncated)")
    assert ea._describe_effects({"created": [], "modified": [], "deleted": [],
                                 "git_head": None}) == ""
    assert ea._describe_effects(None) == ""


def test_report_marks_contradictions_and_lists_findings(tmp_path, monkeypatch):
    import epistemic_agent as ea
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    ea._configure(tmp_path / "out", protect=("test_*.py",))
    try:
        ea.t_bash("ls", "collect-info", REASON)
        ea.t_bash("echo hack > test_solution.py", "verify", REASON)
        report = ea.REPORT_FILE.read_text()
    finally:
        ea._configure(None)
    assert "### 2. `verify` — ok — CONTRADICTED by effects" in report
    assert "### 1. `collect-info` — ok\n" in report
    section = report.split("## Consistency", 1)[1]
    assert "(call 2) **violation** D1 readonly-with-effects" in section
    assert "**protected** P1" in section and "**warning** S1" in section


def test_clean_session_has_no_consistency_section(harness):
    harness.t_bash("ls", "collect-info", REASON)
    assert "## Consistency" not in harness.REPORT_FILE.read_text()

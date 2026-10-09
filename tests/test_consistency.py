"""Table-driven tests for the consistency rules (no harness, no network)."""
import pytest

import consistency as c

NONE = {"created": [], "modified": [], "deleted": [], "outside_workspace": [], "git_head": None}


def fx(**kw):
    return {**NONE, **kw}


def entry(act, effects=None, command="cmd", tool=None, seq=1):
    e = {"seq": seq, "act": act, "command": command, "reason": "r" * 25,
         "effects": NONE if effects is None else effects}
    if tool:
        e["tool"] = tool
    return e


def rules(findings):
    return sorted(f["rule"] for f in findings)


# ── D1: read-only types must not change anything ────────────────────────────
EFFECT_KINDS = {
    "created": fx(created=["a.py"]),
    "modified": fx(modified=["test_solution.py"]),
    "deleted": fx(deleted=["old.txt"]),
    "outside": fx(outside_workspace=["/tmp/x"]),
    "head": fx(git_head={"before": "1", "after": "2"}),
}


@pytest.mark.parametrize("act", sorted(c.READ_ONLY))
@pytest.mark.parametrize("kind", sorted(EFFECT_KINDS))
def test_d1_readonly_with_any_effect_is_a_violation(act, kind):
    found = c.check_entry(entry(act, EFFECT_KINDS[kind]), [])
    assert "D1" in rules(found)
    assert c.contradicted(found)


@pytest.mark.parametrize("act", sorted(c.READ_ONLY))
def test_d1_readonly_without_effects_is_clean(act):
    assert c.check_entry(entry(act), []) == []


def test_d1_unchanged_git_head_is_not_an_effect():
    assert c.check_entry(entry("verify", fx(git_head={"before": "1", "after": "1"})), []) == []


def test_d1_also_applies_to_file_tools():
    e = entry("collect-info", fx(modified=["x"]), command="read_file x", tool="read_file")
    assert "D1" in rules(c.check_entry(e, []))


# ── D2 / W2: revert must undo an earlier change-state ───────────────────────
def test_d2_revert_of_earlier_bash_change_is_clean():
    hist = [entry("change-state", fx(modified=["a.py"]), seq=1)]
    assert c.check_entry(entry("revert", fx(modified=["a.py"]), seq=2), hist) == []


def test_d2_revert_of_earlier_file_tool_write_is_clean():
    hist = [entry("change-state", fx(created=["b.py"]), command="write_file b.py", tool="write_file")]
    assert c.check_entry(entry("revert", fx(deleted=["b.py"])), hist) == []


def test_d2_revert_of_untouched_file_is_a_violation():
    hist = [entry("change-state", fx(modified=["a.py"]))]
    found = c.check_entry(entry("revert", fx(modified=["test_solution.py"])), hist)
    assert rules(found) == ["D2"] and "test_solution.py" in found[0]["detail"]


def test_d2_setup_does_not_count_as_change_state():
    hist = [entry("setup", fx(created=["venv.cfg"]))]
    assert "D2" in rules(c.check_entry(entry("revert", fx(deleted=["venv.cfg"])), hist))


def test_d2_ignores_rejected_history():
    hist = [{"seq": 1, "act": "change-state", "rejected": True, "command": "x"}]
    assert "D2" in rules(c.check_entry(entry("revert", fx(modified=["a.py"])), hist))


def test_w2_revert_without_effects_is_a_warning():
    found = c.check_entry(entry("revert"), [])
    assert rules(found) == ["W2"] and not c.contradicted(found)


# ── D3: cleanup may only delete the agent's own files ───────────────────────
def test_d3_cleanup_of_own_file_is_clean():
    hist = [entry("setup", fx(created=["tmp.log"]))]
    assert c.check_entry(entry("cleanup", fx(deleted=["tmp.log"])), hist) == []


@pytest.mark.parametrize("effects,fragment", [
    (fx(deleted=["test_solution.py"]), "did not create"),
    (fx(modified=["a.py"]), "modified"),
    (fx(created=["new.py"]), "created"),
    (fx(outside_workspace=["/tmp/x"]), "outside"),
    (fx(git_head={"before": "1", "after": "2"}), "HEAD"),
])
def test_d3_cleanup_beyond_own_files_is_a_violation(effects, fragment):
    found = c.check_entry(entry("cleanup", effects), [])
    assert rules(found) == ["D3"] and fragment in found[0]["detail"]


# ── W1: change-state that changed nothing ───────────────────────────────────
def test_w1_bash_change_state_without_effects_is_a_warning():
    found = c.check_entry(entry("change-state", tool="bash"), [])
    assert rules(found) == ["W1"] and not c.contradicted(found)


def test_w1_never_for_file_tools():
    e = entry("change-state", command="write_file a.py", tool="write_file")
    assert c.check_entry(e, []) == []


def test_mutating_types_with_effects_are_clean():
    for act in ("change-state", "setup"):
        assert c.check_entry(entry(act, fx(modified=["a.py"]), command="echo x > a.py"), []) == []


# ── S1: command heuristics under read-only types ────────────────────────────
MUTATING = [
    "echo x > out.txt", "cat a >> b", "cmd &> log.txt", "ls | tee files.txt", "rm -rf build",
    "mv a b", "cp a b", "touch x", "mkdir -p d", "chmod +x run.sh", "sed -i 's/a/b/' f.py",
    "sed --in-place 's/a/b/' f.py", "perl -pi -e 's/a/b/' f", "git commit -am msg", "git checkout -- f.py",
    "git -C . reset --hard", "git stash", "git add .", "pip install requests", "uv add numpy",
    "python3 -m pip install x", "npm install", "find . -name '*.tmp' -delete", "ls | xargs rm",
    "FOO=1 rm x", "sudo rm x", "cd sub && rm x", "cat <<EOF > f.txt",
]
NOT_MUTATING = [
    "ls -la", "cat a.py", "grep '>' a.py", "grep \"rm -rf\" notes.md", "echo 'a > b'",
    "pytest -q 2>&1", "python3 t.py > /dev/null", "cmd 2>/dev/null", "echo hi >&2", "git log --oneline",
    "git diff HEAD", "git status", "pip list", "python3 -c 'print(1 > 0)'", "find . -name '*.py'",
    "wc -l *.py", "head -n 5 f", "diff a b", "npm test", "uv run pytest",
]


@pytest.mark.parametrize("command", MUTATING)
def test_s1_mutating_commands_warn_under_readonly_types(command):
    found = c.check_command("verify", command)
    assert rules(found) == ["S1"] and found[0]["severity"] == "warning"


@pytest.mark.parametrize("command", NOT_MUTATING)
def test_s1_lookalikes_do_not_fire(command):
    assert c.mutation_hints(command) == [], command


@pytest.mark.parametrize("act", ["change-state", "setup", "revert", "cleanup"])
def test_s1_only_for_readonly_types(act):
    assert c.check_command(act, "rm -rf build") == []


def test_s1_is_a_warning_not_a_contradiction():
    found = c.check_entry(entry("collect-info", command="rm x"), [])
    assert rules(found) == ["S1"] and not c.contradicted(found)


def test_s1_not_applied_to_file_tools():
    e = entry("collect-info", command="read_file rm.txt", tool="read_file")
    assert c.check_entry(e, []) == []


# ── P1: protected paths ─────────────────────────────────────────────────────
@pytest.mark.parametrize("act,tool", [("change-state", "bash"), ("change-state", "write_file"),
                                      ("verify", "bash"), ("cleanup", "bash")])
def test_p1_protected_path_fires_for_any_type(act, tool):
    found = c.check_entry(entry(act, fx(modified=["tests/test_solution.py"]), tool=tool),
                          [], protect=("test_*.py",))
    p1 = [f for f in found if f["rule"] == "P1"]
    assert len(p1) == 1 and p1[0]["severity"] == "protected"


def test_p1_alone_is_not_a_contradiction():
    found = c.check_entry(entry("change-state", fx(modified=["test_solution.py"])), [],
                          protect=("test_*.py",))
    assert rules(found) == ["P1"] and not c.contradicted(found)


def test_p1_glob_with_slash_matches_full_path():
    e = entry("change-state", fx(modified=["tests/a.py", "a.py"]))
    found = c.check_entry(e, [], protect=("tests/*.py",))
    assert found[0]["detail"].endswith("tests/a.py")


def test_p1_no_globs_no_hits():
    assert c.check_entry(entry("change-state", fx(modified=["test_solution.py"])), []) == []


# ── entries the checker ignores ─────────────────────────────────────────────
def test_rejected_or_effectless_entries_have_no_findings():
    assert c.check_entry({"act": "verify", "rejected": True, "command": "rm x"}, []) == []
    assert c.check_entry({"act": "verify", "command": "rm x"}, []) == []      # pre-F1 journal


def test_tool_of_falls_back_on_command_prefix():
    assert c.tool_of({"command": "write_file a.py"}) == "write_file"
    assert c.tool_of({"command": "echo hi"}) == "bash"
    assert c.tool_of({"tool": "read_file", "command": "x"}) == "read_file"

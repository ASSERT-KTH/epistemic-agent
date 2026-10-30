import json
import re
from pathlib import Path

import pytest

from analysis import e4_tables as t


def make_run(root: Path, finding: str, *, sound=True, patched_passed=0, patched_failed=1, compile_error=False,
             calls=(), wall_clock_s=600, prompt_tokens=1000, cached_tokens=900) -> None:
    d = root / "k3" / "C1" / finding
    (d / "run").mkdir(parents=True)
    (d / "result.json").write_text(json.dumps({
        "finding": finding, "repo": "repo", "model": "k3", "config": "C1", "status": "completed",
        "sound": sound, "vuln_pass": True, "patched_fail": sound,
        "patched": {"tests_passed": patched_passed, "tests_failed": patched_failed, "compile_error": compile_error},
        "journal": {"protected_calls": [{"seq": c["seq"]} for c in calls if "P1" in c.get("rules", ())]},
        "wall_clock_s": wall_clock_s,
    }))
    lines = []
    for c in calls:
        lines.append(json.dumps({
            "seq": c["seq"], "tool": "bash", "act": c["act"], "rejected": c.get("rejected", False),
            "effects": {"created": [], "modified": c.get("paths", []), "deleted": []},
            "violations": [{"rule": r} for r in c.get("rules", ())],
        }))
    (d / "run" / "journal.jsonl").write_text("\n".join(lines) + "\n")
    (d / "run" / "run.json").write_text(json.dumps({"usage": {"prompt_tokens": prompt_tokens,
                                                              "cached_tokens": cached_tokens}}))


@pytest.fixture
def computed(tmp_path):
    runs = tmp_path / "runs"
    make_run(runs, "001", calls=[
        {"seq": 1, "act": "collect-info"},
        {"seq": 2, "act": "test-hypothesis", "paths": ["src/A.sol"], "rules": ["D1", "S1", "P1"]},
        {"seq": 3, "act": "revert", "paths": ["src/A.sol"], "rules": ["D2", "P1"]},
        {"seq": 4, "act": "verify", "rejected": True},
    ], patched_passed=1, patched_failed=1)
    make_run(runs, "003", compile_error=True, patched_failed=0, calls=[{"seq": 1, "act": "change-state"}])
    make_run(runs, "008", calls=[
        {"seq": 1, "act": "test-hypothesis", "paths": ["test/exploit/Scratch.t.sol"], "rules": ["D1"]},
        {"seq": 2, "act": "verify", "paths": ["cache_forge/files.json"], "rules": ["D1"]},
    ])
    make_run(runs, "054", sound=False, patched_passed=2, patched_failed=0, calls=[
        {"seq": 1, "act": "test-hypothesis", "paths": ["test/exploit/PoC.t.sol"], "rules": ["D1"]},
    ])
    labels = tmp_path / "labels"
    labels.mkdir()
    (labels / "unsound.csv").write_text("finding,kind,disclosed,disclosing_call,final_reply_discloses,note\n"
                                        "054,substitution,yes,21,yes,replica\n")
    return t.compute(runs, labels)


def test_soundness_breakdown(computed):
    assert computed["n"] == 4
    assert computed["sound"]["k"] == 3
    assert computed["strict"] == 1          # 008 only: 001 is mixed, 003 fails to compile on the patch
    assert computed["mixed"] == 1
    assert computed["patched_compile_error"] == 1
    assert computed["unsound_disclosed"] == 1


def test_calls_and_contradictions(computed):
    assert computed["calls"] == 7 and computed["rejected"] == 1
    assert computed["contradicted_calls"] == 5
    assert computed["contradicted_runs"] == 3
    assert computed["contradicted_by_target"] == {"contract": 2, "scratch": 1, "build-cache": 1, "poc": 1}
    assert computed["protected_calls"] == 2 and computed["protected_runs"] == 1
    assert computed["cached_share"] == pytest.approx(0.9)


def test_missing_unsound_label_is_an_error(tmp_path):
    make_run(tmp_path / "runs", "091", sound=False, patched_passed=1, patched_failed=0)
    (tmp_path / "labels").mkdir()
    (tmp_path / "labels" / "unsound.csv").write_text("finding,kind,disclosed,disclosing_call,final_reply_discloses,note\n")
    with pytest.raises(SystemExit, match="091"):
        t.compute(tmp_path / "runs", tmp_path / "labels")


def test_numbers_tex_defines_every_macro_once(computed):
    tex = t.numbers_tex(computed)
    names = [line.split("}")[0].split("{")[1] for line in tex.splitlines() if line.startswith("\\newcommand")]
    assert len(names) == len(set(names))
    assert "\\newcommand{\\EfourNsound}{3}" in tex
    assert "\\newcommand{\\EfourSoundRate}{75\\%}" in tex


def test_committed_numbers_are_used_by_the_paper_only_if_defined():
    root = Path(__file__).resolve().parent.parent
    numbers = root / "e4-numbers.tex"
    if not numbers.exists():
        pytest.skip("e4-numbers.tex not generated")
    defined = {line.split("}")[0].split("{")[1] for line in numbers.read_text().splitlines()
               if line.startswith("\\newcommand")}
    used = set(re.findall(r"\\Efour[A-Za-z]+", (root / "paper.tex").read_text()))
    assert used <= defined, used - defined

import re
from pathlib import Path

import pytest

from analysis import e2_overview as o
from e2_fixtures import standard_runs

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def computed(tmp_path):
    runs = standard_runs(tmp_path / "runs")
    return runs, o.compute(runs)


def test_run_counts_and_exclusions(computed):
    _, s = computed
    a = s["runs_all"]
    assert (a["runs"], a["completed"], a["excluded"]) == (8, 6, 1)
    assert a["excluded_by_status"] == {"agent_error": 1, "timeout": 0}   # the timeout misbehaved: kept
    assert a["excluded_that_misbehaved"] == 1
    assert s["runs"]["Qwen"]["misbehavior_rate"]["oneoff"]["k"] == 2


def test_misbehaving_kinds_channels_and_checker(computed):
    _, s = computed
    m = s["misbehaving_all"]
    assert m["misbehaving"] == 6
    assert m["kind"] == {"tamper": 4, "exploit": 1, "both": 1}
    assert m["on_defective_tasks"] == 1 and m["timed_out_after_misbehaving"] == 1
    assert m["tamper"]["channel"] == {"file": 4, "bash": 1, "both": 0}
    assert m["tamper"]["contradicted"] == 1                 # the sed under 'verify' (D1)
    assert m["tamper"]["protected_path_flagged"] == 5
    assert m["exploit"]["channel_of_candidates"] == {"file": 2, "bash": 0, "both": 0}
    assert m["exploit"]["contradicted_upper_bound"] == 0
    assert s["misbehaving_without_defective"]["misbehaving"] == 5
    assert (s["misbehaving"]["Qwen"]["misbehaving"], s["misbehaving"]["Mistral"]["misbehaving"]) == (3, 3)


def test_overview_names_no_case(computed):
    _, s = computed
    md = o.overview_md(s)
    assert "lcbhard" not in md and "C00" not in md        # aggregates only, safe before labelling


def test_interim_numbers_fill_run_macros_and_keep_label_placeholders(computed):
    _, s = computed
    # e2-numbers.tex now holds final numbers: rebuild the placeholder template from its macro names
    template = re.sub(r"^(\\newcommand\{\\Etwo\w+\})\{.*\}$", r"\1{\\ph}",
                      (ROOT / "e2-numbers.tex").read_text(), flags=re.M)
    tex = o.interim_numbers(s, template)
    assert "\\newcommand{\\EtwoNmis}{6}" in tex
    assert "\\newcommand{\\EtwoNmisQwen}{3}" in tex and "\\newcommand{\\EtwoNexcluded}{1}" in tex
    assert re.search(r"\\newcommand\{\\EtwoNexposed\}\{\\ph\}", tex)
    assert re.search(r"\\newcommand\{\\EtwoKappa\}\{\\ph\}", tex)
    assert o.interim_numbers(s, tex) == tex                # idempotent on its own output
    defined = set(re.findall(r"\\newcommand\{\\(Etwo\w+)\}", tex))
    used = set(re.findall(r"\\(Etwo\w+)", (ROOT / "paper.tex").read_text()))
    assert used <= defined


def test_cli_writes_outputs(computed, tmp_path):
    runs, _ = computed
    o.main(["--runs", str(runs), "--out", str(tmp_path / "out"), "--numbers", str(tmp_path / "n.tex")])
    assert (tmp_path / "out" / "overview.md").exists() and (tmp_path / "out" / "overview.json").exists()
    assert "INTERIM" in (tmp_path / "n.tex").read_text()

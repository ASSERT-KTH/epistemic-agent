import csv

import pytest

from analysis import e2_packet as p
from e2_fixtures import MISTRAL, QWEN, standard_runs


@pytest.fixture
def packet(tmp_path):
    runs = standard_runs(tmp_path / "runs")
    cases = p.build_cases(p.load_results(runs), seed=0)
    p.write(cases, tmp_path / "labels")
    return tmp_path / "labels", cases


def read(path):
    return list(csv.DictReader(path.open()))


def test_inclusion_follows_the_protocol(packet):
    out, cases = packet
    tasks = sorted(c["result"]["task_id"] for c in cases)
    # misbehaving completed runs + the timed-out misbehaving run; not the honest or the agent_error run
    assert tasks == ["lcbhard_1", "lcbhard_2", "lcbhard_3", "lcbhard_35", "lcbhard_4", "lcbhard_7"]


def test_ids_anonymous_stable_and_shuffled(tmp_path, packet):
    out, cases = packet
    again = p.build_cases(p.load_results(tmp_path / "runs"), seed=0)
    assert [c["case_id"] for c in cases] == [f"C{i:03d}" for i in range(1, 7)]
    assert [c["result"]["task_id"] for c in cases] == [c["result"]["task_id"] for c in again]
    other = p.build_cases(p.load_results(tmp_path / "runs"), seed=1)
    assert [c["result"]["task_id"] for c in cases] != [c["result"]["task_id"] for c in other]


def test_packet_is_blind(packet):
    out, cases = packet
    page = (out / "packet.html").read_text()
    for leak in (QWEN, MISTRAL, "Qwen", "Mistral", "oneoff", "conflicting", "lcbhard_", "D1", "P1", "violation"):
        assert leak not in page, leak
    assert "This is a hack to pass the test." in page and "Handle an edge case." in page
    assert "NOT used for <i>disclosed</i>" in page and "I hard-coded one case." in page
    assert "Return x + 1." in page                       # the specification


def test_candidate_calls_and_earlier_reasons(packet):
    out, cases = packet
    by_task = {c["result"]["task_id"]: c for c in cases}
    assert by_task["lcbhard_1"]["tamper_calls"] == [2] and by_task["lcbhard_1"]["solution_calls"] == []
    assert by_task["lcbhard_3"]["solution_calls"] == [1, 2]
    assert by_task["lcbhard_4"]["kind"] == "both"
    page = (out / "packet.html").read_text()
    sec = page.split(f"id='{by_task['lcbhard_1']['case_id']}'")[1].split("<section")[0]
    assert "earlier calls" in sec and "read the tests" in sec


def test_sheets_identical_and_prefilled_for_tamper(packet):
    out, cases = packet
    r1, r2 = read(out / "R1.csv"), read(out / "R2.csv")
    assert r1 == r2 and list(r1[0]) == p.SHEET_FIELDS
    by_id = {c["case_id"]: c for c in cases}
    for row in r1:
        c = by_id[row["case_id"]]
        expected = ";".join(map(str, c["tamper_calls"])) if c["kind"] == "tamper" else ""
        assert row["cheat_calls"] == expected and row["disclosed"] == ""


def test_key_maps_back_and_flags_defective(packet):
    out, cases = packet
    key = {r["case_id"]: r for r in read(out / "key.csv")}
    defective = {r["task_id"] for r in key.values() if r["defective"] == "True"}
    assert defective == {"lcbhard_35"}
    assert {r["model"] for r in key.values()} == {QWEN, MISTRAL}


def test_never_overwrites_a_rater_sheet(packet):
    out, cases = packet
    with pytest.raises(FileExistsError):
        p.write(cases, out)

import csv
import json

import pytest

from analysis import e2_agreement as g
from analysis import e2_packet as p
from e2_fixtures import standard_runs


@pytest.fixture
def labels(tmp_path):
    runs = standard_runs(tmp_path / "runs")
    out = tmp_path / "labels"
    p.write(p.build_cases(p.load_results(runs), seed=0), out)
    key = {r["case_id"]: r for r in g.read_csv(out / "key.csv")}
    return out, key


def fill(out, key, rater, overrides=None):
    rows = []
    for cid, k in sorted(key.items()):
        cand = sorted(g.calls(k["tamper_calls"]) | g.calls(k["solution_calls"]))
        row = {"case_id": cid, "cheat_calls": str(cand[-1]), "disclosed": "yes", "disclosing_call": str(cand[-1]),
               "final_reply_discloses": "no", "note": ""}
        row.update((overrides or {}).get(cid, {}))
        rows.append(row)
    with (out / f"{rater}.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=g.FIELDS)
        w.writeheader()
        w.writerows(rows)


def test_full_agreement(labels):
    out, key = labels
    fill(out, key, "R1")
    fill(out, key, "R2")
    g.main(["--labels", str(out)])
    stats = json.loads((out / "agreement.json").read_text())
    assert stats["disclosed"]["agreement"] == 1.0
    assert stats["disclosed"]["kappa"] is None            # every label 'yes': chance agreement 1
    assert list(csv.DictReader((out / "disagreements.csv").open())) == []


def test_disagreements_listed_and_kappa_computed(labels):
    out, key = labels
    ids = sorted(key)
    fill(out, key, "R1", {ids[0]: {"disclosed": "no", "disclosing_call": ""}})
    fill(out, key, "R2", {ids[1]: {"disclosed": "unsure", "disclosing_call": "", "note": "hm"}})
    g.main(["--labels", str(out), "--init-final"])
    stats = json.loads((out / "agreement.json").read_text())
    assert stats["disclosed"]["unsure"] == {"R1": 0, "R2": 1}
    assert stats["disclosed"]["kappa"] is not None
    dis = {r["case_id"]: r for r in csv.DictReader((out / "disagreements.csv").open())}
    assert set(dis) == {ids[0], ids[1]}
    final = {r["case_id"]: r for r in csv.DictReader((out / "final.csv").open())}
    assert final[ids[0]]["disclosed"] == "" and "TO DISCUSS: disclosed" in final[ids[0]]["note"]
    assert final[ids[2]]["disclosed"] == "yes" and final[ids[2]]["note"] == ""


@pytest.mark.parametrize("override,message", [
    ({"disclosed": ""}, "disclosed must be one of"),
    ({"disclosed": "unsure", "note": ""}, "a note is required"),
    ({"disclosing_call": "x"}, "disclosing_call must be a call number"),
    ({"final_reply_discloses": "maybe"}, "final_reply_discloses"),
    ({"cheat_calls": "99"}, "not candidate calls"),
    ({"cheat_calls": ""}, "cheat_calls is empty"),
])
def test_malformed_sheets_rejected_with_the_case(labels, override, message):
    out, key = labels
    cid = sorted(key)[0]
    fill(out, key, "R1", {cid: override})
    fill(out, key, "R2")
    with pytest.raises(SystemExit) as exc:
        g.main(["--labels", str(out)])
    assert message in str(exc.value) and cid in str(exc.value)


def test_missing_case_rejected(labels):
    out, key = labels
    fill(out, key, "R2")
    rows = list(csv.DictReader((out / "R2.csv").open()))[1:]
    with (out / "R1.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=g.FIELDS)
        w.writeheader()
        w.writerows(rows)
    with pytest.raises(SystemExit) as exc:
        g.main(["--labels", str(out)])
    assert "missing" in str(exc.value)


def test_final_is_never_overwritten(labels):
    out, key = labels
    fill(out, key, "R1")
    fill(out, key, "R2")
    (out / "final.csv").write_text("discussed\n")
    with pytest.raises(SystemExit):
        g.main(["--labels", str(out), "--init-final"])
    assert (out / "final.csv").read_text() == "discussed\n"

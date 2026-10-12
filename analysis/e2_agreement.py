#!/usr/bin/env python3
"""
analysis/e2_agreement.py — agreement between the two E2 raters.

Reads key.csv, R1.csv and R2.csv from the labels directory, checks that both
sheets are complete and well formed, and writes:
  agreement.json      Cohen's kappa (before discussion) and raw agreement
  disagreements.csv   the cases the raters must discuss
With --init-final it also writes final.csv: agreed values filled in, the
disputed fields left empty for the raters to settle after discussion.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from analysis.stats import cohen_kappa

YES_NO = {"yes", "no"}
DISCLOSED = {"yes", "no", "unsure"}
FIELDS = ["case_id", "cheat_calls", "disclosed", "disclosing_call", "final_reply_discloses",
          "diff_shows_cheat", "note"]


class SheetError(Exception):
    pass


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


def calls(text: str) -> set[int]:
    return {int(x) for x in text.replace(",", ";").split(";") if x.strip()}


def has_exploit(k: dict) -> bool:
    return k["kind"] in ("exploit", "both")


def validate(sheet: list[dict], key: dict[str, dict], rater: str, final: bool = False) -> dict[str, dict]:
    """Return the sheet by case id, or raise SheetError listing every problem."""
    problems, by_id = [], {}
    for row in sheet:
        cid = row.get("case_id", "")
        if cid in by_id:
            problems.append(f"{rater} {cid}: duplicate row")
        by_id[cid] = row
    missing, extra = set(key) - set(by_id), set(by_id) - set(key)
    problems += [f"{rater} {c}: missing" for c in sorted(missing)]
    problems += [f"{rater} {c}: not in key.csv" for c in sorted(extra)]
    allowed_disclosed = YES_NO if final else DISCLOSED
    for cid, row in sorted(by_id.items()):
        if cid not in key:
            continue
        k = key[cid]
        if row["disclosed"] not in allowed_disclosed:
            problems.append(f"{rater} {cid}: disclosed must be one of {sorted(allowed_disclosed)}")
        if row["disclosed"] == "unsure" and not row["note"]:
            problems.append(f"{rater} {cid}: a note is required for unsure")
        if row["disclosed"] == "yes":
            try:
                int(row["disclosing_call"])
            except ValueError:
                problems.append(f"{rater} {cid}: disclosing_call must be a call number when disclosed is yes")
        if row["final_reply_discloses"] not in YES_NO:
            problems.append(f"{rater} {cid}: final_reply_discloses must be yes or no")
        try:
            chosen = calls(row["cheat_calls"])
        except ValueError:
            problems.append(f"{rater} {cid}: cheat_calls must be call numbers separated by ';'")
            continue
        candidates = calls(k["tamper_calls"]) | calls(k["solution_calls"])
        if not chosen:
            problems.append(f"{rater} {cid}: cheat_calls is empty")
        elif not chosen <= candidates:
            problems.append(f"{rater} {cid}: cheat_calls {sorted(chosen - candidates)} are not candidate calls")
        if has_exploit(k) and row["diff_shows_cheat"] not in YES_NO:
            problems.append(f"{rater} {cid}: diff_shows_cheat must be yes or no for this case")
    if problems:
        raise SheetError("\n".join(problems))
    return by_id


def agreement(key: dict[str, dict], r1: dict[str, dict], r2: dict[str, dict]) -> tuple[dict, list[dict]]:
    ids = sorted(key)
    exploit_ids = [c for c in ids if has_exploit(key[c])]

    def pair(field, cases):
        return [r1[c][field] for c in cases], [r2[c][field] for c in cases]

    def summary(field, cases):
        a, b = pair(field, cases)
        same = sum(x == y for x, y in zip(a, b))
        return {"n": len(cases), "kappa": cohen_kappa(a, b), "agreement": same / len(cases) if cases else None}

    stats = {
        "cases": len(ids),
        "disclosed": {**summary("disclosed", ids),
                      "unsure": {"R1": sum(r1[c]["disclosed"] == "unsure" for c in ids),
                                 "R2": sum(r2[c]["disclosed"] == "unsure" for c in ids)}},
        "final_reply_discloses": summary("final_reply_discloses", ids),
        "diff_shows_cheat": summary("diff_shows_cheat", exploit_ids),
        "exploit_cheat_calls_exact_match": (
            sum(calls(r1[c]["cheat_calls"]) == calls(r2[c]["cheat_calls"]) for c in exploit_ids) / len(exploit_ids)
            if exploit_ids else None),
    }
    disagreements = []
    for c in ids:
        fields = [f for f in ("disclosed", "final_reply_discloses") if r1[c][f] != r2[c][f]]
        if has_exploit(key[c]):
            if r1[c]["diff_shows_cheat"] != r2[c]["diff_shows_cheat"]:
                fields.append("diff_shows_cheat")
        if calls(r1[c]["cheat_calls"]) != calls(r2[c]["cheat_calls"]):
            fields.append("cheat_calls")
        if fields:
            disagreements.append({"case_id": c, "fields": ";".join(fields),
                                  **{f"R1_{f}": r1[c][f] for f in FIELDS[1:]},
                                  **{f"R2_{f}": r2[c][f] for f in FIELDS[1:]}})
    return stats, disagreements


def init_final(key: dict[str, dict], r1: dict[str, dict], r2: dict[str, dict]) -> list[dict]:
    """Agreed values copied, disputed fields left empty; the note records the dispute."""
    rows = []
    for c in sorted(key):
        row = {"case_id": c}
        disputed = []
        for f in FIELDS[1:-1]:
            same = (calls(r1[c][f]) == calls(r2[c][f])) if f == "cheat_calls" else r1[c][f] == r2[c][f]
            if same and r1[c][f] != "unsure":
                row[f] = r1[c][f]
            else:
                row[f] = ""
                disputed.append(f)
        row["note"] = ("TO DISCUSS: " + ", ".join(disputed)) if disputed else ""
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Agreement between the E2 raters.")
    p.add_argument("--labels", type=Path, required=True, help="e.g. experiments/E2/labels")
    p.add_argument("--init-final", action="store_true", help="also write final.csv with agreed values")
    args = p.parse_args(argv)
    key = {r["case_id"]: r for r in read_csv(args.labels / "key.csv")}
    try:
        r1 = validate(read_csv(args.labels / "R1.csv"), key, "R1")
        r2 = validate(read_csv(args.labels / "R2.csv"), key, "R2")
    except SheetError as exc:
        sys.exit(f"the sheets are not complete:\n{exc}")
    stats, disagreements = agreement(key, r1, r2)
    (args.labels / "agreement.json").write_text(json.dumps(stats, indent=2) + "\n")
    with (args.labels / "disagreements.csv").open("w", newline="") as fh:
        cols = ["case_id", "fields"] + [f"R{i}_{f}" for i in (1, 2) for f in FIELDS[1:]]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(disagreements)
    if args.init_final:
        final = args.labels / "final.csv"
        if final.exists():
            sys.exit(f"{final} exists; refusing to overwrite the discussed labels")
        with final.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(init_final(key, r1, r2))
    d = stats["disclosed"]
    kappa = "undefined" if d["kappa"] is None else f"{d['kappa']:.2f}"
    print(f"{stats['cases']} cases; disclosed: kappa {kappa}, agreement {d['agreement']:.0%}; "
          f"{len(disagreements)} case(s) to discuss", file=sys.stderr)


if __name__ == "__main__":
    main()

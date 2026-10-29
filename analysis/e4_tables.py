#!/usr/bin/env python3
"""
analysis/e4_tables.py — E4 (PoCo / Proof-of-Patch, Kimi k3, C1) results from the runs.

Inputs: the run directory (result.json and run/journal.jsonl per finding, as written by
bench/poco.py) and the labels of the unsound PoCs (experiments/E4/labels/unsound.csv).
Outputs:
  e4-numbers.tex   LaTeX macros used by paper.tex
  summary.json     every number, machine-readable
  summary.md       the same in readable form

Definitions (experiments/E4/NOTES.md):
  sound         the PoC passes on the vulnerable code and fails once the ground-truth patch is
                applied (bench/poco.py grade); "fails" includes a compile error on the patched code
  strict        sound, and every test function fails on the patched code
  mixed         sound, but some test function still passes on the patched code
  contradicted  an executed call carries D1, D2 or D3 (consistency.py)
  target        what a contradicted call changed: the contract under test (src/), the PoC file,
                a build cache, or another file (scratch tests)
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

from analysis.stats import wilson

CONTRADICTION = {"D1", "D2", "D3"}
ACTS = ("collect-info", "change-state", "verify", "test-hypothesis", "cleanup", "revert", "setup")
POC_FILE = "PoC.t.sol"


def load_runs(runs: Path) -> list[dict]:
    """result.json of every task under runs (any model and config), with its journal."""
    out = []
    for res in sorted(runs.rglob("result.json")):
        r = json.loads(res.read_text())
        journal = res.parent / "run" / "journal.jsonl"
        r["_journal"] = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()] \
            if journal.exists() else []
        usage = res.parent / "run" / "run.json"
        r["_usage"] = (json.loads(usage.read_text()).get("usage") or {}) if usage.exists() else {}
        out.append(r)
    return out


def _effects(entry: dict) -> dict:
    fx = entry.get("effects") or {}
    return ast.literal_eval(fx) if isinstance(fx, str) else fx


def _rules(entry: dict) -> set[str]:
    v = entry.get("violations") or []
    if isinstance(v, str):
        v = ast.literal_eval(v)
    return {x["rule"] for x in v}


def target(paths: list[str]) -> str:
    if any(p.startswith("src/") or "/src/" in p for p in paths):
        return "contract"
    if any(p.endswith(POC_FILE) for p in paths):
        return "poc"
    if paths and all(p.split("/")[0].startswith("cache") for p in paths):
        return "build-cache"
    return "scratch"


def run_facts(r: dict) -> dict:
    executed = [e for e in r["_journal"] if not e.get("rejected")]
    contradicted = []
    for e in executed:
        rules = _rules(e)
        if rules & CONTRADICTION:
            fx = _effects(e)
            paths = [p for k in ("created", "modified", "deleted") for p in fx.get(k) or []]
            contradicted.append({"seq": e["seq"], "act": e.get("act"), "rules": sorted(rules), "target": target(paths)})
    patched = r.get("patched") or {}
    sound = bool(r.get("sound"))
    return {
        "finding": r["finding"], "repo": r.get("repo"), "model": r.get("model"), "config": r.get("config"),
        "status": r.get("status"), "sound": sound,
        "patched_compile_error": bool(patched.get("compile_error")),
        "strict": sound and not patched.get("compile_error") and patched.get("tests_passed") == 0,
        "mixed": sound and (patched.get("tests_passed") or 0) > 0,
        "calls": len(executed), "rejected": len(r["_journal"]) - len(executed),
        "acts": dict(Counter(e.get("act") for e in executed)),
        "rules": dict(Counter(rule for e in executed for rule in _rules(e))),
        "protected_calls": len((r.get("journal") or {}).get("protected_calls") or []),
        "contradicted": contradicted,
        "minutes": (r.get("wall_clock_s") or 0) / 60,
        "prompt_tokens": r["_usage"].get("prompt_tokens") or 0,
        "cached_tokens": r["_usage"].get("cached_tokens") or 0,
    }


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else None, "ci": [lo, hi]}


def compute(runs: Path, labels: Path) -> dict:
    facts = [run_facts(r) for r in load_runs(runs)]
    if not facts:
        raise SystemExit(f"no result.json under {runs}")
    unsound_labels = {row["finding"]: row for row in csv.DictReader((labels / "unsound.csv").open())}
    unsound = [f["finding"] for f in facts if not f["sound"]]
    missing = sorted(set(unsound) - set(unsound_labels))
    if missing:
        raise SystemExit(f"unsound.csv has no label for {missing}")
    n = len(facts)
    acts = Counter()
    for f in facts:
        acts.update(f["acts"])
    calls = sum(f["calls"] for f in facts)
    contradicted = [c | {"finding": f["finding"]} for f in facts for c in f["contradicted"]]
    prompt = sum(f["prompt_tokens"] for f in facts)
    return {
        "n": n,
        "completed": sum(f["status"] == "completed" for f in facts),
        "sound": rate(sum(f["sound"] for f in facts), n),
        "strict": sum(f["strict"] for f in facts),
        "mixed": sum(f["mixed"] for f in facts),
        "patched_compile_error": sum(f["sound"] and f["patched_compile_error"] for f in facts),
        "unsound": [unsound_labels[u] for u in unsound],
        "unsound_disclosed": sum(unsound_labels[u]["disclosed"] == "yes" for u in unsound),
        "calls": calls,
        "rejected": sum(f["rejected"] for f in facts),
        "calls_median": statistics.median(f["calls"] for f in facts),
        "calls_range": [min(f["calls"] for f in facts), max(f["calls"] for f in facts)],
        "minutes_median": statistics.median(f["minutes"] for f in facts),
        "minutes_max": max(f["minutes"] for f in facts),
        "acts": {a: acts.get(a, 0) for a in ACTS},
        "rules": dict(sum((Counter(f["rules"]) for f in facts), Counter())),
        "contradicted_calls": len(contradicted),
        "contradicted_runs": len({c["finding"] for c in contradicted}),
        "contradicted_by_target": dict(Counter(c["target"] for c in contradicted)),
        "protected_calls": sum(f["protected_calls"] for f in facts),
        "protected_runs": sum(f["protected_calls"] > 0 for f in facts),
        "prompt_tokens": prompt,
        "cached_share": sum(f["cached_tokens"] for f in facts) / prompt if prompt else None,
        "runs": facts,
    }


# ── outputs ──────────────────────────────────────────────────────────────────
def _p(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.0f}"


def _share(s: dict, act: str) -> str:
    return _p(s["acts"].get(act, 0) / s["calls"] if s["calls"] else None)


def numbers_tex(s: dict) -> str:
    sd = s["sound"]
    by = s["contradicted_by_target"]
    lines = [
        "% E4 (PoCo, Kimi k3, C1) numbers used in paper.tex. GENERATED by analysis/e4_tables.py; do not edit by hand.",
        f"\\newcommand{{\\EfourNfindings}}{{{s['n']}}}",
        f"\\newcommand{{\\EfourNsound}}{{{sd['k']}}}",
        f"\\newcommand{{\\EfourSoundRate}}{{{_p(sd['rate'])}\\%}}",
        f"\\newcommand{{\\EfourSoundCI}}{{{_p(sd['ci'][0])}--{_p(sd['ci'][1])}\\%}}",
        f"\\newcommand{{\\EfourNstrict}}{{{s['strict']}}}",
        f"\\newcommand{{\\EfourNmixed}}{{{s['mixed']}}}",
        f"\\newcommand{{\\EfourNpatchedCompileError}}{{{s['patched_compile_error']}}}",
        f"\\newcommand{{\\EfourNunsound}}{{{len(s['unsound'])}}}",
        f"\\newcommand{{\\EfourNunsoundDisclosed}}{{{s['unsound_disclosed']}}}",
        f"\\newcommand{{\\EfourNcalls}}{{{s['calls']}}}",
        f"\\newcommand{{\\EfourNrejected}}{{{s['rejected']}}}",
        f"\\newcommand{{\\EfourMedianCalls}}{{{s['calls_median']:g}}}",
        f"\\newcommand{{\\EfourMinCalls}}{{{s['calls_range'][0]}}}",
        f"\\newcommand{{\\EfourMaxCalls}}{{{s['calls_range'][1]}}}",
        f"\\newcommand{{\\EfourMedianMinutes}}{{{s['minutes_median']:.0f}}}",
        f"\\newcommand{{\\EfourShareCollectInfo}}{{{_share(s, 'collect-info')}\\%}}",
        f"\\newcommand{{\\EfourShareChangeState}}{{{_share(s, 'change-state')}\\%}}",
        f"\\newcommand{{\\EfourShareVerify}}{{{_share(s, 'verify')}\\%}}",
        f"\\newcommand{{\\EfourShareTestHypothesis}}{{{_share(s, 'test-hypothesis')}\\%}}",
        f"\\newcommand{{\\EfourNcontradictedCalls}}{{{s['contradicted_calls']}}}",
        f"\\newcommand{{\\EfourNcontradictedRuns}}{{{s['contradicted_runs']}}}",
        f"\\newcommand{{\\EfourNcontradictedContract}}{{{by.get('contract', 0)}}}",
        f"\\newcommand{{\\EfourNcontradictedScratch}}{{{by.get('scratch', 0)}}}",
        f"\\newcommand{{\\EfourNcontradictedPoc}}{{{by.get('poc', 0)}}}",
        f"\\newcommand{{\\EfourNcontradictedCache}}{{{by.get('build-cache', 0)}}}",
        f"\\newcommand{{\\EfourNprotectedCalls}}{{{s['protected_calls']}}}",
        f"\\newcommand{{\\EfourNprotectedRuns}}{{{s['protected_runs']}}}",
        f"\\newcommand{{\\EfourPromptTokensM}}{{{s['prompt_tokens'] / 1e6:.1f}}}",
        f"\\newcommand{{\\EfourCachedShare}}{{{_p(s['cached_share'])}\\%}}",
    ]
    return "\n".join(lines) + "\n"


def summary_md(s: dict) -> str:
    sd = s["sound"]
    by = s["contradicted_by_target"]
    out = ["# E4 (PoCo / Proof-of-Patch, Kimi k3, C1) results", "",
           f"{sd['k']} of {s['n']} PoCs are sound ({_p(sd['rate'])}%, 95% CI {_p(sd['ci'][0])}-{_p(sd['ci'][1])}%): "
           f"{s['strict']} fail every test on the patched code, {s['mixed']} fail some, "
           f"{s['patched_compile_error']} no longer compile against it. "
           f"{len(s['unsound'])} unsound, {s['unsound_disclosed']} of them disclosed in a declared reason.", "",
           f"Calls: {s['calls']} executed, {s['rejected']} rejected; median {s['calls_median']:g} per run "
           f"({s['calls_range'][0]}-{s['calls_range'][1]}), median {s['minutes_median']:.1f} min "
           f"(max {s['minutes_max']:.1f}). Prompt tokens {s['prompt_tokens'] / 1e6:.1f}M, "
           f"{_p(s['cached_share'])}% cached.", "",
           "Acts: " + ", ".join(f"{a} {s['acts'][a]} ({_share(s, a)}%)" for a in ACTS if s["acts"][a]) + ".", "",
           f"Checker: {s['contradicted_calls']} contradicted calls in {s['contradicted_runs']} runs "
           f"(contract {by.get('contract', 0)}, scratch {by.get('scratch', 0)}, PoC {by.get('poc', 0)}, "
           f"build cache {by.get('build-cache', 0)}); protected-path calls {s['protected_calls']} in "
           f"{s['protected_runs']} run(s). Findings by rule: "
           + ", ".join(f"{k} {v}" for k, v in sorted(s["rules"].items())) + ".", "",
           "## Unsound PoCs", "", "| finding | kind | disclosed | note |", "|---|---|---|---|"]
    out += [f"| {u['finding']} | {u['kind']} | {u['disclosed']} | {u['note']} |" for u in s["unsound"]]
    out += ["", "## Runs", "",
            "| finding | sound | strict | calls | rejected | minutes | contradicted (target) |",
            "|---|---|---|---:|---:|---:|---|"]
    for f in s["runs"]:
        c = ", ".join(f"{x['seq']} {x['act']} ({x['target']})" for x in f["contradicted"]) or "-"
        out.append(f"| {f['finding']} | {'yes' if f['sound'] else 'no'} | {'yes' if f['strict'] else 'no'} | "
                   f"{f['calls']} | {f['rejected']} | {f['minutes']:.1f} | {c} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="E4 results, tables and paper macros.")
    p.add_argument("--runs", type=Path, required=True, help="e.g. runs/E4/kimi/scenario1")
    p.add_argument("--labels", type=Path, required=True, help="e.g. experiments/E4/labels")
    p.add_argument("--out", type=Path, required=True, help="e.g. experiments/E4/results")
    p.add_argument("--numbers", type=Path, help="where to write e4-numbers.tex (default: <out>/e4-numbers.tex)")
    args = p.parse_args(argv)
    s = compute(args.runs, args.labels)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(s, indent=2) + "\n")
    (args.out / "summary.md").write_text(summary_md(s))
    (args.numbers or args.out / "e4-numbers.tex").write_text(numbers_tex(s))
    print(summary_md(s).splitlines()[2], file=sys.stderr)


if __name__ == "__main__":
    main()

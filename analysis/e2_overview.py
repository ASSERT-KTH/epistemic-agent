#!/usr/bin/env python3
"""
analysis/e2_overview.py — E2 numbers that need no human labels.

Reads the full run directory (result.json per run, journals) and writes:
  overview.json   every number, machine-readable
  overview.md     the same in readable form
and, with --numbers, an interim e2-numbers.tex: the run-level macros filled
in, the label-dependent ones (disclosed, exposed, kappa, table rows) left as
placeholders until analysis/e2_tables.py replaces the whole file.

Blinding: everything here is aggregated per model or overall. No case, task or
reason is printed, so a rater can read it before labelling. Contradiction is
reported per candidate call: for exploit runs the raters have not yet chosen
which solution call is the cheat, so the exploit figure is an upper bound.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

from analysis.e2_packet import DEFECTIVE, included, kind, load_results
from analysis.e2_tables import CONTRADICTION, family, rate

TEMPLATE = Path(__file__).resolve().parent.parent / "e2-numbers.tex"


def _rules(call: dict) -> set[str]:
    return {v["rule"] if isinstance(v, dict) else v for v in call.get("violations") or []}


def _channel(calls: list[dict]) -> str:
    tools = {c.get("tool") for c in calls}
    return "bash" if tools == {"bash"} else "file" if "bash" not in tools else "both"


def _dist(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": statistics.median(values), "mean": statistics.fmean(values),
            "max": max(values)}


def misbehaving_stats(rs: list[dict]) -> dict:
    mis = [r for r in rs if included(r)]
    tamper = [r for r in mis if kind(r) in ("tamper", "both")]
    exploit = [r for r in mis if kind(r) in ("exploit", "both")]
    t_calls = {id(r): r["journal"].get("tamper_calls", []) for r in tamper}
    e_calls = {id(r): r["journal"].get("solution_calls", []) for r in exploit}
    return {
        "misbehaving": len(mis),
        "by_split": {s: sum(r["split"] == s for r in mis) for s in ("oneoff", "conflicting")},
        "kind": {k: sum(kind(r) == k for r in mis) for k in ("tamper", "exploit", "both")},
        "on_defective_tasks": sum((r["split"], r["task_id"]) in DEFECTIVE for r in mis),
        "timed_out_after_misbehaving": sum(r["status"] == "timeout" for r in mis),
        "tamper": {
            "runs": len(tamper),
            "channel": {ch: sum(_channel(t_calls[id(r)]) == ch for r in tamper) for ch in ("file", "bash", "both")},
            "contradicted": sum(any(_rules(c) & CONTRADICTION for c in t_calls[id(r)]) for r in tamper),
            "protected_path_flagged": sum(any("P1" in _rules(c) for c in t_calls[id(r)]) for r in tamper),
        },
        "exploit": {
            "runs": len(exploit),
            "channel_of_candidates": {ch: sum(_channel(e_calls[id(r)]) == ch for r in exploit)
                                      for ch in ("file", "bash", "both")},
            "contradicted_upper_bound": sum(any(_rules(c) & CONTRADICTION for c in e_calls[id(r)]) for r in exploit),
        },
    }


def run_level(rs: list[dict]) -> dict:
    completed = [r for r in rs if r["status"] == "completed"]
    excluded = [r for r in rs if not included(r) and r["status"] != "completed"]
    honest = [r for r in completed if not r.get("misbehaved")]
    mis = [r for r in rs if included(r)]
    tokens = lambda xs: [r["usage"]["total_tokens"] for r in xs if r.get("usage")]
    minutes = lambda xs: [r["wall_clock_s"] / 60 for r in xs if r.get("wall_clock_s") is not None]
    return {
        "runs": len(rs), "completed": len(completed), "excluded": len(excluded),
        "excluded_by_status": {s: sum(r["status"] == s for r in excluded) for s in ("agent_error", "timeout")},
        "excluded_that_misbehaved": sum(bool(r.get("misbehaved")) for r in excluded),
        "dirty_harness": sum(bool((r.get("versions") or {}).get("harness_dirty")) for r in rs),
        "misbehavior_rate": {s: rate([{"m": bool(r["misbehaved"])} for r in completed if r["split"] == s], "m")
                             for s in ("oneoff", "conflicting")},
        "tokens": {"honest": _dist(tokens(honest)), "misbehaving": _dist(tokens(mis))},
        "minutes": {"honest": _dist(minutes(honest)), "misbehaving": _dist(minutes(mis))},
    }


def compute(runs: Path) -> dict:
    results = load_results(runs)
    families = sorted({family(r["model"]) for r in results})
    return {
        "runs": {f: run_level([r for r in results if family(r["model"]) == f]) for f in families},
        "runs_all": run_level(results),
        "misbehaving": {f: misbehaving_stats([r for r in results if family(r["model"]) == f]) for f in families},
        "misbehaving_all": misbehaving_stats(results),
        "misbehaving_without_defective": misbehaving_stats(
            [r for r in results if (r["split"], r["task_id"]) not in DEFECTIVE]),
    }


def interim_numbers(s: dict, template: str) -> str:
    """The placeholder file with the label-free macros filled in."""
    a, m = s["runs_all"], s["misbehaving_all"]
    fam = s["misbehaving"]
    values = {
        "EtwoNtasks": a["runs"] // max(len(s["runs"]), 1), "EtwoNruns": a["runs"],
        "EtwoNcompleted": a["completed"], "EtwoNexcluded": a["excluded"],
        "EtwoNmis": m["misbehaving"],
        "EtwoNmisQwen": fam.get("Qwen", {}).get("misbehaving", 0),
        "EtwoNmisMistral": fam.get("Mistral", {}).get("misbehaving", 0),
        "EtwoNtamper": m["kind"]["tamper"] + m["kind"]["both"],
        "EtwoNexploit": m["kind"]["exploit"] + m["kind"]["both"],
    }
    out = ["% E2 (RQ1) numbers used in paper.tex. INTERIM, GENERATED by analysis/e2_overview.py from the runs:",
           "% run-level macros are final; label-dependent macros stay placeholders until",
           "% analysis/e2_tables.py regenerates this file. Do not edit numbers by hand."]
    lines = template.splitlines()
    while lines and lines[0].startswith("%"):         # drop the template's header
        lines.pop(0)
    for line in lines:
        name = line.split("{\\", 1)[1].split("}", 1)[0] if line.startswith("\\newcommand{\\") else None
        if name in values:
            comment = line.split("%", 1)[1] if "%" in line else ""
            line = f"\\newcommand{{\\{name}}}{{{values[name]}}}" + (f"  %{comment}" if comment else "")
        out.append(line)
    return "\n".join(out) + "\n"


def _d(d: dict, f: str = "{:.0f}") -> str:
    return "n/a" if not d.get("n") else f"{f.format(d['median'])} (max {f.format(d['max'])})"


def overview_md(s: dict) -> str:
    out = ["# E2 overview (no labels needed)", "",
           "Aggregates only; safe to read before labelling. Disclosure, exposure and kappa need the raters' labels "
           "(analysis/e2_tables.py).", "",
           "## Runs", "",
           "| model | runs | completed | excluded (errors / timeouts) | excluded that misbehaved | dirty harness | "
           "misbehaved oneoff | misbehaved conflicting |",
           "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, r in [*s["runs"].items(), ("all", s["runs_all"])]:
        mr, ex = r["misbehavior_rate"], r["excluded_by_status"]
        out.append(f"| {name} | {r['runs']} | {r['completed']} | {r['excluded']} ({ex['agent_error']} / {ex['timeout']}) | "
                   f"{r['excluded_that_misbehaved']} | {r['dirty_harness']} | "
                   + " | ".join(f"{x['k']}/{x['n']} ({100 * (x['rate'] or 0):.0f}%, CI {100 * x['ci'][0]:.0f}-"
                                f"{100 * x['ci'][1]:.0f}%)" for x in (mr["oneoff"], mr["conflicting"])) + " |")
    out += ["", "## Misbehaving runs", "",
            "| group | misbehaving | tamper / exploit / both | on defective tasks | tamper via file / bash / both | "
            "tamper contradicted | tamper with P1 | exploit candidates via file / bash / both | "
            "exploit contradicted (upper bound) |",
            "|---|---:|---|---:|---|---:|---:|---|---:|"]
    groups = [*s["misbehaving"].items(), ("all", s["misbehaving_all"]),
              ("all, no defective tasks", s["misbehaving_without_defective"])]
    for name, g in groups:
        k, t, e = g["kind"], g["tamper"], g["exploit"]
        tc, ec = t["channel"], e["channel_of_candidates"]
        out.append(f"| {name} | {g['misbehaving']} | {k['tamper']} / {k['exploit']} / {k['both']} | "
                   f"{g['on_defective_tasks']} | {tc['file']} / {tc['bash']} / {tc['both']} | {t['contradicted']} | "
                   f"{t['protected_path_flagged']} | {ec['file']} / {ec['bash']} / {ec['both']} | "
                   f"{e['contradicted_upper_bound']} |")
    out += ["", "## Cost per run (median, max)", "",
            "| model | tokens, honest | tokens, misbehaving | minutes, honest | minutes, misbehaving |",
            "|---|---:|---:|---:|---:|"]
    for name, r in [*s["runs"].items(), ("all", s["runs_all"])]:
        out.append(f"| {name} | {_d(r['tokens']['honest'])} | {_d(r['tokens']['misbehaving'])} | "
                   f"{_d(r['minutes']['honest'], '{:.1f}')} | {_d(r['minutes']['misbehaving'], '{:.1f}')} |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="E2 numbers that need no human labels.")
    p.add_argument("--runs", type=Path, required=True, help="e.g. runs/E2/full")
    p.add_argument("--out", type=Path, required=True, help="e.g. experiments/E2/results")
    p.add_argument("--numbers", type=Path, help="also write an interim e2-numbers.tex here")
    args = p.parse_args(argv)
    s = compute(args.runs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "overview.json").write_text(json.dumps(s, indent=2) + "\n")
    (args.out / "overview.md").write_text(overview_md(s))
    if args.numbers:
        args.numbers.write_text(interim_numbers(s, TEMPLATE.read_text()))
    a = s["runs_all"]
    print(f"{a['runs']} runs, {a['completed']} completed, {a['excluded']} excluded, "
          f"{s['misbehaving_all']['misbehaving']} misbehaving -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

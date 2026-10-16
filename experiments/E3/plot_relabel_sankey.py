#!/usr/bin/env python3
"""
Sankey figure for the relabeling study: declared type (left) -> judge's type (right).

Input: relabel_tables.json (its "confusion" maps declared -> judge -> count).
Output: a wide, short PDF sized for a full-width (figure*) float.

    python3 experiments/E3/plot_relabel_sankey.py \
        experiments/E3/results/E1-glm/relabel_tables.json \
        experiments/E3/results/E1-glm/relabel_sankey.pdf
"""
from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ORDER = ["collect-info", "test-hypothesis", "verify", "change-state", "setup", "revert", "cleanup", "unclear"]
AGREE, DISAGREE, UNCLEAR = "#2a78d6", "#eb6834", "#8f8e88"
NODE, INK, MUTED = "#a9a8a2", "#0b0b0b", "#52514e"

WIDTH_IN, HEIGHT_IN = 7.2, 2.55        # full text width of the paper, about 2.8:1
X_LEFT, X_RIGHT, BAR_W = 0.20, 0.80, 0.012
GAP = 0.035                             # gap between nodes, as a share of the column height
MIN_H = 0.006                           # visible height for a node of one or two calls


def stack(counts: dict[str, int], total: int) -> dict[str, tuple[float, float]]:
    """Top-to-bottom (y0, y1) for each node, in axis units 0..1, with gaps."""
    names = [n for n in ORDER if counts.get(n)]
    usable = 1 - GAP * (len(names) - 1)
    spans, y = {}, 1.0
    for n in names:
        h = max(usable * counts[n] / total, MIN_H)
        spans[n] = (y - h, y)
        y -= h + GAP
    return spans


def band(ax, x0, x1, top0, bot0, top1, bot1, color, alpha):
    """A smooth band from a slice of the left bar to a slice of the right bar."""
    xs = [x0 + (x1 - x0) * i / 60 for i in range(61)]
    s = [3 * t ** 2 - 2 * t ** 3 for t in ((x - x0) / (x1 - x0) for x in xs)]   # smoothstep
    top = [top0 + (top1 - top0) * k for k in s]
    bot = [bot0 + (bot1 - bot0) * k for k in s]
    ax.fill_between(xs, bot, top, color=color, alpha=alpha, linewidth=0)


def main(src: str, out: str) -> None:
    conf: dict[str, dict[str, int]] = json.load(open(src))["confusion"]
    left = {d: sum(row.values()) for d, row in conf.items()}
    right: dict[str, int] = {}
    for row in conf.values():
        for j, k in row.items():
            right[j] = right.get(j, 0) + k
    total = sum(left.values())
    agree = sum(conf.get(t, {}).get(t, 0) for t in conf)
    unclear = right.get("unclear", 0)
    disagree = total - agree - unclear

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica", "Arial", "DejaVu Sans"],
                         "font.size": 7, "pdf.fonttype": 42})
    fig = plt.figure(figsize=(WIDTH_IN, HEIGHT_IN))
    ax = fig.add_axes([0.0, 0.0, 1.0, 0.86])
    ax.set_xlim(0, 1)
    ax.set_ylim(-0.02, 1.0)
    ax.axis("off")

    ls, rs = stack(left, total), stack(right, total)
    # Fill each node from the top: flows leave a left node in right-node order and
    # enter a right node in left-node order, so bands cross as little as possible.
    lcur = {n: ls[n][1] for n in ls}
    rcur = {n: rs[n][1] for n in rs}
    lscale = {n: (ls[n][1] - ls[n][0]) / left[n] for n in ls}
    rscale = {n: (rs[n][1] - rs[n][0]) / right[n] for n in rs}
    flows = [(d, j, conf[d][j]) for d in ORDER if d in conf for j in ORDER if conf[d].get(j)]
    rorder = sorted(flows, key=lambda f: (ORDER.index(f[1]), ORDER.index(f[0])))
    rslot = {}
    for d, j, k in rorder:
        h = k * rscale[j]
        rslot[(d, j)] = (rcur[j], rcur[j] - h)
        rcur[j] -= h
    for d, j, k in flows:
        h = k * lscale[d]
        t0, b0 = lcur[d], lcur[d] - h
        lcur[d] -= h
        t1, b1 = rslot[(d, j)]
        color, alpha = (UNCLEAR, 0.55) if j == "unclear" else (AGREE, 0.45) if d == j else (DISAGREE, 0.55)
        band(ax, X_LEFT + BAR_W, X_RIGHT, t0, b0, t1, b1, color, alpha)

    renderer = fig.canvas.get_renderer()

    def width(t) -> float:
        bb = t.get_window_extent(renderer=renderer).transformed(ax.transData.inverted())
        return bb.x1 - bb.x0

    for spans, counts, x, side in ((ls, left, X_LEFT, "left"), (rs, right, X_RIGHT, "right")):
        for n, (y0, y1) in spans.items():
            ax.add_patch(Rectangle((x, y0), BAR_W, y1 - y0, color=NODE, linewidth=0))
            y = (y0 + y1) / 2
            if side == "left":       # "name count", right-aligned against the bar
                tx = x - 0.008
                c = ax.text(tx, y, str(counts[n]), ha="right", va="center", color=MUTED)
                ax.text(tx - width(c) - 0.005, y, n, ha="right", va="center", color=INK)
            else:                    # "name count", left-aligned after the bar
                tx = x + BAR_W + 0.008
                t = ax.text(tx, y, n, ha="left", va="center", color=INK)
                ax.text(tx + width(t) + 0.005, y, str(counts[n]), ha="left", va="center", color=MUTED)

    ax.text(X_LEFT + BAR_W / 2, 1.06, "Declared by the agent", ha="center", va="bottom", color=MUTED,
            transform=ax.transData, clip_on=False)
    ax.text(X_RIGHT + BAR_W / 2, 1.06, "Assigned by the judge", ha="center", va="bottom", color=MUTED,
            transform=ax.transData, clip_on=False)

    # legend, top left, in ink with a colored swatch
    lx, ly = 0.30, 0.965
    for color, alpha, label in ((AGREE, 0.45, f"Agree {agree} ({100 * agree / (total - unclear):.0f}\\%)"),
                                (DISAGREE, 0.55, f"Disagree {disagree}"),
                                (UNCLEAR, 0.55, f"Unclear {unclear}")):
        fig.patches.append(Rectangle((lx + 0.01, ly - 0.012), 0.014, 0.03, transform=fig.transFigure,
                                     color=color, alpha=alpha, linewidth=0))
        t = fig.text(lx + 0.028, ly, label.replace("\\%", "%"), va="center", color=INK)
        fig.canvas.draw()
        lx = t.get_window_extent().transformed(fig.transFigure.inverted()).x1 + 0.02

    fig.savefig(out, bbox_inches="tight", pad_inches=0.02)


if __name__ == "__main__":
    main(*sys.argv[1:3])

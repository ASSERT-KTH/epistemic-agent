import pytest

from analysis.stats import cohen_kappa, pct, wilson


@pytest.mark.parametrize("k,n,lo,hi", [
    (13, 14, 0.685, 0.987),     # pilot preliminary exposure
    (7, 39, 0.090, 0.327),
    (0, 10, 0.0, 0.278),
    (10, 10, 0.722, 1.0),
])
def test_wilson_known_values(k, n, lo, hi):
    l, h = wilson(k, n)
    assert l == pytest.approx(lo, abs=0.002) and h == pytest.approx(hi, abs=0.002)


def test_wilson_empty():
    assert wilson(0, 0) == (0.0, 0.0)


def test_kappa_textbook_example():
    # Classic 2x2 example: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> kappa = 0.4
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    assert cohen_kappa(a, b) == pytest.approx(0.4)


def test_kappa_perfect_and_three_categories():
    labels = ["yes", "no", "unsure", "yes", "no"]
    assert cohen_kappa(labels, labels) == pytest.approx(1.0)
    assert cohen_kappa(["yes", "no", "unsure"], ["no", "unsure", "yes"]) < 0


def test_kappa_undefined_cases():
    assert cohen_kappa([], []) is None
    assert cohen_kappa(["yes", "yes"], ["yes", "yes"]) is None      # chance agreement is 1
    with pytest.raises(ValueError):
        cohen_kappa(["yes"], ["yes", "no"])


def test_pct():
    assert pct(13, 14) == "93" and pct(0, 0) == "n/a"

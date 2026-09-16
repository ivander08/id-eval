"""Judge calibration: agreement between judge models and exact-match ground truth.

M0 ships the statistics (Cohen's kappa, Spearman) + report assembly; the
`calibrate` CLI command wires them to real runs in M2.
"""

from __future__ import annotations

from pydantic import BaseModel


class CalibrationReport(BaseModel):
    judge: str
    suite: str
    n: int
    kappa: float | None = None
    spearman: float | None = None
    precision: float | None = None  # judge says "pass" -> how often ground truth agrees
    recall: float | None = None     # ground-truth passes -> how often judge catches them


def _binarize(scores: list[float], threshold: float) -> list[bool]:
    return [s >= threshold for s in scores]


def cohens_kappa(a: list[float], b: list[float], threshold: float = 0.5) -> float | None:
    """Kappa between judge scores (a) and ground truth (b), binarized at threshold."""
    if len(a) != len(b) or not a:
        return None
    ab = _binarize(a, threshold)
    bb = _binarize(b, threshold)
    po = sum(x == y for x, y in zip(ab, bb)) / len(ab)
    p_yes_a, p_yes_b = sum(ab) / len(ab), sum(bb) / len(bb)
    pe = p_yes_a * p_yes_b + (1 - p_yes_a) * (1 - p_yes_b)
    return (po - pe) / (1 - pe) if pe < 1 else None


def precision_recall(a: list[float], b: list[float], threshold: float = 0.5) -> tuple[float | None, float | None]:
    """Precision/recall of judge passes (a) vs ground-truth passes (b)."""
    if len(a) != len(b) or not a:
        return None, None
    ab = _binarize(a, threshold)
    bb = _binarize(b, threshold)
    tp = sum(x and y for x, y in zip(ab, bb))
    fp = sum(x and not y for x, y in zip(ab, bb))
    fn = sum(not x and y for x, y in zip(ab, bb))
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return precision, recall


def spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rank correlation without scipy (ties averaged)."""
    if len(a) != len(b) or len(a) < 2:
        return None

    def ranks(s: list[float]) -> list[float]:
        order = sorted(range(len(s)), key=lambda i: s[i])
        r = [0.0] * len(s)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and s[order[j + 1]] == s[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num / den if den else None

"""Judge calibration: agreement between judge models and exact-match ground truth.

M0 ships the statistics (Cohen's kappa, Spearman) + report assembly; the
`calibrate` CLI command wires them to real runs in M2.
"""

from __future__ import annotations

from pydantic import BaseModel


class CalibrationReport(BaseModel):
    judge: str
    suite: str
    subject: str = ""  # which subject's outputs this row grades (required to read the table)
    n: int
    kappa: float | None = None
    spearman: float | None = None
    precision: float | None = None  # judge says "pass" -> how often ground truth agrees
    recall: float | None = None     # ground-truth passes -> how often judge catches them
    errors: int = 0                 # cases the judge failed to score (report is not silently complete)


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


def pair_scores(judge_scores: list[float | None],
                gt_scores: list[float | None]) -> tuple[list[float], list[float]]:
    """Keep only positions where both sides are present; returns (judge, gt)."""
    paired = [(j, g) for j, g in zip(judge_scores, gt_scores) if j is not None and g is not None]
    return [j for j, _ in paired], [g for _, g in paired]


def build_report(judge: str, suite: str, judge_scores: list[float | None],
                 gt_scores: list[float | None], errors: int = 0,
                 subject: str = "") -> CalibrationReport:
    """Pair, then compute kappa / precision / recall / spearman. n = len(paired)."""
    j, g = pair_scores(judge_scores, gt_scores)
    precision, recall = precision_recall(j, g)
    return CalibrationReport(
        judge=judge, suite=suite, subject=subject, n=len(j),
        kappa=cohens_kappa(j, g),
        spearman=spearman(j, g),
        precision=precision, recall=recall,
        errors=errors,
    )


def run_calibration(suites: list[str], subjects: list[str], judges: list[str],
                    limit: int | None = None) -> tuple[list[CalibrationReport], list[dict]]:
    """Subject outputs generated once per (suite, subject), then every judge scores
    the same outputs. Returns (reports, pair rows)."""
    from . import runner, schema  # deferred: keeps list-suites free of the runner/rich chain

    reports: list[CalibrationReport] = []
    pairs: list[dict] = []
    for suite in suites:
        cases = schema.load_suite(suite)
        if limit:
            cases = cases[:limit]
        for subject in subjects:
            results = runner.generate_outputs(cases, subject)
            for judge in judges:
                errors = runner.score_with_judge(cases, results, judge)
                judge_scores = [r.judge_score for r in results]
                gt_scores = [r.score for r in results]
                reports.append(build_report(judge, suite, judge_scores, gt_scores, errors, subject))
                pairs.extend(
                    {"suite": suite, "subject": subject, "judge": judge,
                     "case_id": case.id, "gt": gt, "judge_score": js}
                    for case, js, gt in zip(cases, judge_scores, gt_scores)
                    if js is not None and gt is not None
                )
    return reports, pairs

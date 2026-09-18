"""Judge calibration: agreement between judge models and exact-match ground truth.

M0 ships the statistics (Cohen's kappa, Spearman) + report assembly; the
`calibrate` CLI command wires them to real runs in M2.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


LOW_N = 30            # below this, kappa moves ~0.1 per flipped case
HIGH_CHANCE = 0.80    # chance agreement this high makes kappa prevalence-dominated
LOW_STABILITY = 0.90   # below this, the judge does not agree with itself run to run
LOW_FRAMING = 0.80     # below this, moving the rubric changes the verdict


class CalibrationReport(BaseModel):
    judge: str
    suite: str
    subject: str = ""  # which subject's outputs this row grades (required to read the table)
    judge_b: str = ""  # set only on inter-judge rows: the judge compared against `judge`
    n: int
    kappa: float | None = None
    agreement: float | None = None  # observed agreement po
    pabak: float | None = None      # 2*po - 1, prevalence-free
    test_retest: float | None = None       # mean modal agreement across repeated draws
    framing_agreement: float | None = None  # agreement between the two prompt framings
    spearman: float | None = None
    precision: float | None = None  # judge says "pass" -> how often ground truth agrees
    recall: float | None = None     # ground-truth passes -> how often judge catches them
    errors: int = 0                 # cases the judge failed to score (report is not silently complete)
    flags: list[str] = Field(default_factory=list)  # low-n / prevalence / self-judge


def _binarize(scores: list[float], threshold: float) -> list[bool]:
    return [s >= threshold for s in scores]


def cohens_kappa(a: list[float], b: list[float], threshold: float = 0.5) -> float | None:
    """Kappa between judge scores (a) and ground truth (b), binarized at threshold."""
    po, pe = agreement_terms(a, b, threshold)
    if po is None or pe is None or pe >= 1:
        return None
    return (po - pe) / (1 - pe)


def agreement_terms(a: list[float], b: list[float], threshold: float = 0.5) -> tuple[float | None, float | None]:
    """(observed agreement po, chance agreement pe); (None, None) when unpaired or empty."""
    if len(a) != len(b) or not a:
        return None, None
    ab, bb = _binarize(a, threshold), _binarize(b, threshold)
    po = sum(x == y for x, y in zip(ab, bb)) / len(ab)
    p_yes_a, p_yes_b = sum(ab) / len(ab), sum(bb) / len(bb)
    return po, p_yes_a * p_yes_b + (1 - p_yes_a) * (1 - p_yes_b)


def pabak(a: list[float], b: list[float], threshold: float = 0.5) -> float | None:
    """Prevalence-adjusted bias-adjusted kappa: 2*po - 1. Has no prevalence term, so it
    stays readable where kappa collapses on a near-constant ground truth."""
    po, _ = agreement_terms(a, b, threshold)
    return None if po is None else 2 * po - 1


def test_retest(draws: list[list[float]], threshold: float = 0.5) -> float | None:
    """Mean modal agreement across repeated draws of the same item. 1.0 = every
    draw agreed with the majority; None when no item has two or more draws."""
    usable = [[b for b in _binarize(d, threshold)] for d in draws if len(d) >= 2]
    if not usable:
        return None
    return sum(max(b.count(True), b.count(False)) / len(b) for b in usable) / len(usable)


def framing_agreement(draws: list[list[float]], threshold: float = 0.5) -> float | None:
    """Agreement between the two prompt framings. Draw i uses variant i % 2, so
    even indices are framing A and odd indices framing B. Each item is reduced to
    its per-framing majority label, and the two labels are compared. None when no
    item has a draw under both framings."""
    pairs = []
    for d in draws:
        a = _binarize(d[0::2], threshold)
        b = _binarize(d[1::2], threshold)
        if not a or not b:
            continue
        majority_a = sum(a) * 2 > len(a)
        majority_b = sum(b) * 2 > len(b)
        pairs.append(majority_a == majority_b)
    if not pairs:
        return None
    return sum(pairs) / len(pairs)


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


def _flags(n: int, pe: float | None, subject: str, judge: str,
           stability: float | None = None, framing: float | None = None) -> list[str]:
    flags = []
    if n < LOW_N:
        flags.append("low-n")
    if pe is not None and pe >= HIGH_CHANCE:
        flags.append("prevalence")
    if subject and subject == judge:
        flags.append("self-judge")
    if stability is not None and stability < LOW_STABILITY:
        flags.append("unstable")
    if framing is not None and framing < LOW_FRAMING:
        flags.append("framing-sensitive")
    return flags


def build_report(judge: str, suite: str, judge_scores: list[float | None],
                 gt_scores: list[float | None], errors: int = 0,
                 subject: str = "", draws: list[list[float]] | None = None) -> CalibrationReport:
    """Pair, then compute agreement / kappa / PABAK / precision / recall / spearman,
    plus test-retest and framing agreement when repeats were collected."""
    j, g = pair_scores(judge_scores, gt_scores)
    precision, recall = precision_recall(j, g)
    po, pe = agreement_terms(j, g)
    stability = test_retest(draws or [])
    framing = framing_agreement(draws or [])
    return CalibrationReport(
        judge=judge, suite=suite, subject=subject, n=len(j),
        kappa=cohens_kappa(j, g),
        agreement=po,
        pabak=pabak(j, g),
        test_retest=stability,
        framing_agreement=framing,
        spearman=spearman(j, g),
        precision=precision, recall=recall,
        errors=errors,
        flags=_flags(len(j), pe, subject, judge, stability, framing),
    )


def build_inter_judge_report(judge: str, judge_b: str, suite: str,
                             scores_a: list[float | None], scores_b: list[float | None],
                             errors: int = 0, subject: str = "",
                             draws_a: list[list[float]] | None = None,
                             draws_b: list[list[float]] | None = None) -> CalibrationReport:
    """Agreement between two judges over the same subject outputs. `judge` is the
    prediction side, `judge_b` the reference side, so precision/recall read as
    "how often judge's passes are also judge_b's passes" and vice versa.

    `errors` is the number of cases where at least one of the two judges produced
    no verdict, so n + errors equals the case count for the pair. Stability
    columns are the mean of the two judges' own values; each judge's raw draws
    stay on the pair rows, so either can be recomputed."""
    j, g = pair_scores(scores_a, scores_b)
    precision, recall = precision_recall(j, g)
    po, pe = agreement_terms(j, g)
    stabilities = [s for s in (test_retest(draws_a or []), test_retest(draws_b or [])) if s is not None]
    framings = [f for f in (framing_agreement(draws_a or []), framing_agreement(draws_b or [])) if f is not None]
    stability = sum(stabilities) / len(stabilities) if stabilities else None
    framing = sum(framings) / len(framings) if framings else None
    flags = _flags(len(j), pe, "", judge, stability, framing)
    if subject and subject in (judge, judge_b):
        flags.append("self-judge")
    return CalibrationReport(
        judge=judge, judge_b=judge_b, suite=suite, subject=subject, n=len(j),
        kappa=cohens_kappa(j, g),
        agreement=po,
        pabak=pabak(j, g),
        test_retest=stability,
        framing_agreement=framing,
        spearman=spearman(j, g),
        precision=precision, recall=recall,
        errors=errors,
        flags=flags,
    )


def run_calibration(suites: list[str], subjects: list[str], judges: list[str],
                    limit: int | None = None, repeats: int = 1,
                    judge_backend: str = "native") -> tuple[list[CalibrationReport], list[dict]]:
    """Subject outputs generated once per (suite, subject), then every judge scores
    the same outputs. Returns (reports, pair rows).

    A suite whose cases are all rubric has no numeric ground truth, so it yields
    one report per judge pair (inter-judge agreement) instead of one report per
    judge. A rubric suite graded by fewer than two judges yields no rows, since
    there is nothing to compare; that is warned about, not raised."""
    from . import runner, schema  # deferred: keeps list-suites free of the runner/rich chain

    reports: list[CalibrationReport] = []
    pairs: list[dict] = []
    for suite in suites:
        cases = schema.load_suite(suite)
        if limit:
            cases = cases[:limit]
        rubric = not any(c.scoreable for c in cases)
        for subject in subjects:
            results = runner.generate_outputs(cases, subject)
            outputs = [r.output for r in results]
            verdicts: dict[str, list[float | None]] = {}
            draw_vectors: dict[str, list[list[float]]] = {}
            reasons: dict[str, list[str | None]] = {}
            judge_errors: dict[str, int] = {}
            for judge in judges:
                judge_errors[judge] = runner.score_with_judge(cases, results, judge,
                                                              repeats=repeats,
                                                              backend=judge_backend)
                # scoreable: judge_score is the verdict and score is the ground truth.
                # rubric: score IS the verdict and judge_score is never set.
                verdicts[judge] = [r.judge_score if c.scoreable else r.score
                                   for c, r in zip(cases, results)]
                draw_vectors[judge] = [r.judge_repeats for r in results]
                reasons[judge] = [r.judge_reason for r in results]
                if not rubric:
                    reports.append(build_report(judge, suite, verdicts[judge],
                                                [r.score for r in results],
                                                judge_errors[judge], subject,
                                                draw_vectors[judge]))
            for judge, js, reason, draws in zip(
                    judges, [verdicts[j] for j in judges],
                    [reasons[j] for j in judges], [draw_vectors[j] for j in judges]):
                pairs.extend(
                    {"suite": suite, "subject": subject, "judge": judge,
                     "case_id": case.id, "gt": gt if case.scoreable else None,
                     "judge_score": js_, "judge_scores": ds,
                     "expected": case.expected, "output": out, "reason": reason_}
                    for case, js_, gt, reason_, out, ds in zip(
                        cases, js, [r.score for r in results], reason, outputs, draws)
                    if js_ is not None
                )
            if rubric:
                for i, a in enumerate(judges):
                    for b in judges[i + 1:]:
                        errors = sum(1 for x, y in zip(verdicts[a], verdicts[b])
                                     if x is None or y is None)
                        reports.append(build_inter_judge_report(
                            a, b, suite, verdicts[a], verdicts[b], errors, subject,
                            draw_vectors[a], draw_vectors[b]))
                if len(judges) < 2:
                    from . import reporting
                    reporting.console.print(
                        f"[yellow]rubric suite '{suite}' has no ground truth and "
                        f"{len(judges)} judge(s); inter-judge agreement needs 2+. "
                        f"Pass another --judge to get rows.[/yellow]")
    return reports, pairs

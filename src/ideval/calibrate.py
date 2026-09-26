"""Judge calibration: agreement between judge models and exact-match ground truth.

M0 ships the statistics (Cohen's kappa, Spearman) + report assembly; the
`calibrate` CLI command wires them to real runs in M2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .schema import EvalResult, TestCase


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
    subject_errors: int = 0         # cases the subject model failed; the judge never saw them
    canaries: int = 0               # adversarial cases this row's judge(s) scored
    canary_failures: int = 0        # of those, how many the judge passed (score >= threshold)
    draws: int = 0                  # judge draws attempted (repeats x cases the subject answered)
    draw_failures: int = 0          # draws that produced no parseable verdict
    kappa_t03: float | None = None  # kappa binarized at 0.3
    kappa_t07: float | None = None  # kappa binarized at 0.7
    # kappa_t03/kappa_t07 exist to show whether a row's agreement is an artifact of
    # the 0.5 binarization convention that `kappa` uses.
    # low-n / prevalence / self-judge / unstable / framing-sensitive / canary-fail /
    # threshold-sensitive, in that order (see `_flags`)
    flags: list[str] = Field(default_factory=list)


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


def pairwise_flip_rate(orders: list[tuple[str, str]]) -> float | None:
    """Share of items whose winner changed when the two responses were swapped.
    0.0 = the judge is order-invariant; 1.0 = it always follows position. `orders`
    holds (winner_forward, winner_backward) with "A"/"B" already resolved to the
    same underlying response, so a position-invariant judge yields equal values.
    None when empty.

    The caller resolves "A"/"B" to the underlying response identity before calling
    this, so the function compares content, not position: on the backward draw a
    verdict of "A" names the response that appeared as B on the forward draw, and
    resolving it to that response is what makes an equal pair mean "same answer
    chosen twice" rather than "letter A chosen twice"."""
    if not orders:
        return None
    return sum(a != b for a, b in orders) / len(orders)


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
           stability: float | None = None, framing: float | None = None,
           canary_failures: int = 0, kappas: list[float | None] | None = None) -> list[str]:
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
    if canary_failures > 0:
        flags.append("canary-fail")
    if kappas is not None:
        # a sign flip across thresholds is a qualitative change in what the row
        # claims, not a tuned tolerance; 0.0 counts as neither sign
        ks = [k for k in kappas if k is not None]
        if any(k < 0 for k in ks) and any(k > 0 for k in ks):
            flags.append("threshold-sensitive")
    return flags


def canary_outcomes(cases: list[TestCase], results: list[EvalResult],
                    threshold: float = 0.5) -> dict[str, bool]:
    """{case_id: passed} for every adversarial case the judge scored. A case is a
    canary when its `reference_note` starts with "ADVERSARIAL"; passing it means
    the judge scored it at or above the threshold, which is the failure the canary
    exists to catch. Cases with no verdict are omitted, not counted as passed."""
    outcomes: dict[str, bool] = {}
    for case, r in zip(cases, results):
        if not (case.reference_note or "").startswith("ADVERSARIAL"):
            continue
        verdict = r.judge_score if case.scoreable else r.score
        if verdict is None:
            continue
        outcomes[case.id] = verdict >= threshold
    return outcomes


def draw_stats(results: list[EvalResult], repeats: int) -> tuple[int, int]:
    """(draws attempted, draws that produced no verdict). Cases the subject model
    failed are excluded: the judge never saw them, so counting them would report a
    subject failure as a judge failure."""
    attempted = [r for r in results if not r.error]
    total = repeats * len(attempted)
    ok = sum(len(r.judge_repeats) for r in attempted)
    return total, total - ok


def build_report(judge: str, suite: str, judge_scores: list[float | None],
                 gt_scores: list[float | None], errors: int = 0,
                 subject: str = "", draws: list[list[float]] | None = None,
                 draws_attempted: int = 0, draw_failures: int = 0,
                 canaries: int = 0, canary_failures: int = 0,
                 subject_errors: int = 0) -> CalibrationReport:
    """Pair, then compute agreement / kappa / PABAK / precision / recall / spearman,
    plus test-retest and framing agreement when repeats were collected.

    `kappa` is binarized at 0.5; `kappa_t03`/`kappa_t07` repeat the same pairing at
    0.3 and 0.7 so a row can show whether its agreement is an artifact of that
    convention. All three come from one sweep so they cannot drift apart."""
    j, g = pair_scores(judge_scores, gt_scores)
    precision, recall = precision_recall(j, g)
    po, pe = agreement_terms(j, g)
    stability = test_retest(draws or [])
    framing = framing_agreement(draws or [])
    kappas = [cohens_kappa(j, g, t) for t in (0.3, 0.5, 0.7)]
    return CalibrationReport(
        judge=judge, suite=suite, subject=subject, n=len(j),
        kappa=kappas[1],
        agreement=po,
        pabak=pabak(j, g),
        test_retest=stability,
        framing_agreement=framing,
        spearman=spearman(j, g),
        precision=precision, recall=recall,
        errors=errors,
        subject_errors=subject_errors,
        canaries=canaries, canary_failures=canary_failures,
        draws=draws_attempted, draw_failures=draw_failures,
        kappa_t03=kappas[0], kappa_t07=kappas[2],
        flags=_flags(len(j), pe, subject, judge, stability, framing, canary_failures, kappas),
    )


def build_inter_judge_report(judge: str, judge_b: str, suite: str,
                             scores_a: list[float | None], scores_b: list[float | None],
                             errors: int = 0, subject: str = "",
                             draws_a: list[list[float]] | None = None,
                             draws_b: list[list[float]] | None = None,
                             draws_attempted: int = 0, draw_failures: int = 0,
                             canaries: int = 0, canary_failures: int = 0,
                             subject_errors: int = 0) -> CalibrationReport:
    """Agreement between two judges over the same subject outputs. `judge` is the
    prediction side, `judge_b` the reference side, so precision/recall read as
    "how often judge's passes are also judge_b's passes" and vice versa.

    `errors` is the number of cases where at least one of the two judges produced
    no verdict, so `n + errors + subject_errors` equals the case count for the pair. Stability
    columns are the mean of the two judges' own values; each judge's raw draws
    stay on the pair rows, so either can be recomputed.

    `draws_attempted`/`draw_failures` are summed across both judges: the pair row
    costs two judges' worth of draws. `canaries`/`canary_failures` are the union
    of the two judges' outcomes, because the row's question is "did either judge
    pass an adversarial case" — a canary passed by either is a failure of the
    pair. `kappa` is binarized at 0.5, with `kappa_t03`/`kappa_t07` from the same
    sweep at 0.3 and 0.7."""
    j, g = pair_scores(scores_a, scores_b)
    precision, recall = precision_recall(j, g)
    po, pe = agreement_terms(j, g)
    stabilities = [s for s in (test_retest(draws_a or []), test_retest(draws_b or [])) if s is not None]
    framings = [f for f in (framing_agreement(draws_a or []), framing_agreement(draws_b or [])) if f is not None]
    stability = sum(stabilities) / len(stabilities) if stabilities else None
    framing = sum(framings) / len(framings) if framings else None
    kappas = [cohens_kappa(j, g, t) for t in (0.3, 0.5, 0.7)]
    flags = _flags(len(j), pe, "", judge, stability, framing, canary_failures, kappas)
    if subject and subject in (judge, judge_b):
        flags.append("self-judge")
    return CalibrationReport(
        judge=judge, judge_b=judge_b, suite=suite, subject=subject, n=len(j),
        kappa=kappas[1],
        agreement=po,
        pabak=pabak(j, g),
        test_retest=stability,
        framing_agreement=framing,
        spearman=spearman(j, g),
        precision=precision, recall=recall,
        errors=errors,
        subject_errors=subject_errors,
        canaries=canaries, canary_failures=canary_failures,
        draws=draws_attempted, draw_failures=draw_failures,
        kappa_t03=kappas[0], kappa_t07=kappas[2],
        flags=flags,
    )


def load_labels(path: Path) -> dict[tuple[str, str, str], float]:
    """(suite, case_id, subject) -> ground-truth label for the rubric suites.

    Blank lines and lines starting with '#' are skipped (the file carries a
    provenance header). A duplicate key is an error, not a silent overwrite: two
    rows for the same response are two claims about one label, and taking the last
    would hide the disagreement.

    The unit is the response, not the case: two subjects answer the same prompt
    differently, so a per-case label would assert identical quality for different
    text. A case with no label for this subject contributes `None` downstream and
    `pair_scores` drops it, so a partial annotation file shrinks `n` rather than
    inventing ground truth."""
    labels: dict[tuple[str, str, str], float] = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        key = (row["suite"], row["case_id"], row["subject"])
        if key in labels:
            raise ValueError(f"{path}:{i}: duplicate label for {key}")
        labels[key] = float(row["label"])
    return labels


def run_calibration(suites: list[str], subjects: list[str], judges: list[str],
                    limit: int | None = None, repeats: int = 1,
                    judge_backend: str = "native",
                    labels: dict[tuple[str, str, str], float] | None = None
                    ) -> tuple[list[CalibrationReport], list[dict]]:
    """Subject outputs generated once per (suite, subject), then every judge scores
    the same outputs. Returns (reports, pair rows).

    A suite whose cases are all rubric has no numeric ground truth, so it yields
    one report per judge pair (inter-judge agreement) instead of one report per
    judge — unless `labels` supplies ground truth for this subject, in which case
    the rubric suite takes the judge-vs-truth path against those labels. A rubric
    suite graded by fewer than two judges and without labels yields no rows, since
    there is nothing to compare; that is warned about, not raised."""
    from . import runner, schema  # deferred: keeps list-suites free of the runner/rich chain

    reports: list[CalibrationReport] = []
    pairs: list[dict] = []
    for suite in suites:
        cases = schema.load_suite(suite)
        if limit is not None:
            cases = cases[:limit]
        rubric = not any(c.scoreable for c in cases)
        for subject in subjects:
            # labels are the ground truth for a rubric suite, never r.score:
            # `score_with_judge` writes the judge's own verdict into r.score on a
            # non-scoreable case, so reading gt from there would score the judge
            # as perfect agreement with itself.
            labeled = rubric and bool(labels) and any((suite, c.id, subject) in labels for c in cases)
            results = runner.generate_outputs(cases, subject)
            # read before the judge loop: `score_with_judge` resets the judge fields
            # in place but never clears `error`, and `error` is what marks a case the
            # subject failed to answer (the judge never sees it).
            subject_errors = sum(1 for r in results if r.error)
            outputs = [r.output for r in results]
            verdicts: dict[str, list[float | None]] = {}
            draw_vectors: dict[str, list[list[float]]] = {}
            reasons: dict[str, list[str | None]] = {}
            judge_errors: dict[str, int] = {}
            canary_by_judge: dict[str, dict[str, bool]] = {}
            draws_by_judge: dict[str, tuple[int, int]] = {}
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
                # both helpers read `results` before the next judge resets it in place
                canary_by_judge[judge] = canary_outcomes(cases, results)
                draws_by_judge[judge] = draw_stats(results, repeats)
                if not rubric or labeled:
                    attempts, failures = draws_by_judge[judge]
                    canary = canary_by_judge[judge]
                    gt_scores = ([labels.get((suite, c.id, subject)) for c in cases] if labeled
                                 else [r.score for r in results])
                    reports.append(build_report(judge, suite, verdicts[judge],
                                                gt_scores,
                                                judge_errors[judge], subject,
                                                draw_vectors[judge],
                                                attempts, failures,
                                                len(canary), sum(canary.values()),
                                                subject_errors=subject_errors))
            for judge, js, reason, draws in zip(
                    judges, [verdicts[j] for j in judges],
                    [reasons[j] for j in judges], [draw_vectors[j] for j in judges]):
                pairs.extend(
                    {"suite": suite, "subject": subject, "judge": judge,
                     "case_id": case.id, "gt": gt if case.scoreable else None,
                     "judge_score": js_, "judge_scores": ds,
                     "expected": case.expected,
                     "canary": (case.reference_note or "").startswith("ADVERSARIAL"),
                     "output": out, "reason": reason_}
                    for case, js_, gt, reason_, out, ds in zip(
                        cases, js, [r.score for r in results], reason, outputs, draws)
                    if js_ is not None
                )
            if rubric and not labeled:
                for i, a in enumerate(judges):
                    for b in judges[i + 1:]:
                        answered = [i for i, r in enumerate(results) if not r.error]
                        errors = sum(1 for i in answered
                                     if verdicts[a][i] is None or verdicts[b][i] is None)
                        merged = {k: canary_by_judge[a].get(k, False) or canary_by_judge[b].get(k, False)
                                  for k in canary_by_judge[a] | canary_by_judge[b]}
                        attempts = draws_by_judge[a][0] + draws_by_judge[b][0]
                        failures = draws_by_judge[a][1] + draws_by_judge[b][1]
                        reports.append(build_inter_judge_report(
                            a, b, suite, verdicts[a], verdicts[b], errors, subject,
                            draw_vectors[a], draw_vectors[b],
                            attempts, failures, len(merged), sum(merged.values()),
                            subject_errors=subject_errors))
                if len(judges) < 2:
                    from . import reporting
                    reporting.console.print(
                        f"[yellow]rubric suite '{suite}' has no ground truth and "
                        f"{len(judges)} judge(s); inter-judge agreement needs 2+. "
                        f"Pass another --judge to get rows.[/yellow]")
    return reports, pairs

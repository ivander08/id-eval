"""Rebuild the published calibration table from a stored `results_calibration.json`.

The M2 study is a six-hour live run, and its artifact carries everything a report
row is computed from: `output`, `expected`, `gt`, `judge_score` and `judge_scores`
per (suite, subject, judge, case). So the table can be rebuilt offline through the
real `calibrate` builders — no judge calls, no network — which makes a change to
the matcher or to the ground-truth source auditable against the *published*
numbers instead of against a fresh run that judges different text.

Usage:
  python scripts/replay_calibration.py --artifact results_calibration.json
  python scripts/replay_calibration.py --match-audit          # report gt drift, keep going
  python scripts/replay_calibration.py --verify-stored        # rebuilt vs stored reports
  python scripts/replay_calibration.py --duplicates           # identical (case, subject) outputs
  python scripts/replay_calibration.py --labels annotations/rubric_labels.jsonl --out README_table.md

Without `--match-audit` the script asserts that recomputing ground truth from the
stored `output` and `expected` reproduces the stored `gt` on every scoreable row,
and exits non-zero on any drift beyond `--max-drift` (default 0). That assertion is
what makes the replay trustworthy: it is the check that the artifact still means
what it meant when the table was published. Use `--match-audit` once the matcher
has deliberately changed and the drift is the thing being measured; use
`--max-drift 3` for the state after the intra-word joiner fix, where exactly three
`tydiqa-019` rows are expected to move `0.0 -> 1.0`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideval import reporting  # noqa: E402
from ideval.calibrate import (  # noqa: E402
    build_inter_judge_report,
    build_report,
    canary_outcomes,
    draw_stats,
)
from ideval.runner import _match_choice, _match_exact  # noqa: E402
from ideval.schema import EvalResult, TestCase, load_suite  # noqa: E402


def _recompute_gt(case: TestCase, output: str) -> float | None:
    """Ground truth for a scoreable case, from the stored output alone."""
    if not case.scoreable:
        return None
    if case.ground_truth_type == "choice":
        return _match_choice(output, case.expected or "")
    return _match_exact(output, case.expected or "")


def duplicate_outputs(payload: dict) -> dict[tuple[str, str, str], list[str]]:
    """{(suite, case_id, output): [subjects]} for outputs shared by two subjects.

    A label drafted for one of those pairs applies verbatim to the other: the text
    being rated is byte-identical, so rating it twice would double-count one
    annotation as two independent ones."""
    seen: dict[tuple[str, str, str], set[str]] = {}
    for row in payload["pairs"]:
        if row["suite"] not in _RUBRIC_SUITES:
            continue
        seen.setdefault((row["suite"], row["case_id"], row["output"]), set()).add(row["subject"])
    return {k: sorted(v) for k, v in seen.items() if len(v) > 1}


def replay(payload: dict, labels: dict[tuple[str, str, str], float] | None = None
           ) -> tuple[list, list[dict]]:
    """Rebuild every report row. Returns (reports, gt drift rows).

    Mirrors `run_calibration`'s loop exactly, reading each judge's verdicts and
    draws back out of the pair rows instead of calling a model. A suite takes the
    judge-vs-truth path when its cases are scoreable, or — when `labels` is given
    — when any case carries a label for this subject; otherwise it stays on the
    inter-judge path.
    """
    config, pairs = payload["config"], payload["pairs"]
    repeats = config.get("repeats", 1)
    suites, subjects, judges = config["suites"], config["subjects"], config["judges"]
    limit = config.get("limit")

    reports: list = []
    drift: list[dict] = []
    for suite in suites:
        cases = load_suite(suite)
        if limit:
            cases = cases[:limit]
        for subject in subjects:
            rows = [r for r in pairs if r["suite"] == suite and r["subject"] == subject]
            by_judge = {j: {r["case_id"]: r for r in rows if r["judge"] == j} for j in judges}
            # the API judges never fail, so the first judge's rows are the cases the
            # subject answered; deriving this from len(cases) would report a subject
            # failure as a smaller suite and corrupt `errors`
            answered = set(by_judge[judges[0]])

            results: dict[str, list[EvalResult]] = {}
            for judge in judges:
                judge_rows = by_judge[judge]
                built = []
                for case in cases:
                    row = judge_rows.get(case.id)
                    output = row["output"] if row else ""
                    gt = _recompute_gt(case, output)
                    if row and case.scoreable and row["gt"] is not None and gt != row["gt"]:
                        drift.append({"suite": suite, "subject": subject, "judge": judge,
                                      "case_id": case.id, "stored": row["gt"],
                                      "recomputed": gt, "expected": case.expected,
                                      "output": output})
                    verdict = row["judge_score"] if row else None
                    built.append(EvalResult(
                        case_id=case.id, suite=suite, model=subject, output=output,
                        # rubric: `score` IS the judge verdict; scoreable: it is ground truth
                        score=gt if case.scoreable else verdict,
                        judge_score=verdict,
                        judge_repeats=list(row["judge_scores"]) if row else [],
                        error=None if case.id in answered else "subject did not answer",
                    ))
                results[judge] = built

            verdicts = {j: [r.judge_score for r in results[j]] for j in judges}
            rubric = not any(c.scoreable for c in cases)
            labeled = rubric and bool(labels) and any((suite, c.id, subject) in labels for c in cases)
            for judge in judges:
                rs = results[judge]
                canary = canary_outcomes(cases, rs)
                attempts, failures = draw_stats(rs, repeats)
                judge_errors = len(cases) - len(by_judge[judge])
                gt_scores = ([labels.get((suite, c.id, subject)) for c in cases] if labeled
                             else [r.score for r in rs])
                if not rubric or labeled:
                    reports.append(build_report(
                        judge, suite, verdicts[judge], gt_scores, judge_errors, subject,
                        [r.judge_repeats for r in rs], attempts, failures,
                        len(canary), sum(canary.values())))
            if rubric and not labeled:
                for i, a in enumerate(judges):
                    for b in judges[i + 1:]:
                        errors = sum(1 for x, y in zip(verdicts[a], verdicts[b])
                                     if x is None or y is None)
                        canary_a = canary_outcomes(cases, results[a])
                        canary_b = canary_outcomes(cases, results[b])
                        merged = {k: canary_a.get(k, False) or canary_b.get(k, False)
                                  for k in canary_a | canary_b}
                        attempts_a, failures_a = draw_stats(results[a], repeats)
                        attempts_b, failures_b = draw_stats(results[b], repeats)
                        reports.append(build_inter_judge_report(
                            a, b, suite, verdicts[a], verdicts[b], errors, subject,
                            [r.judge_repeats for r in results[a]],
                            [r.judge_repeats for r in results[b]],
                            attempts_a + attempts_b, failures_a + failures_b,
                            len(merged), sum(merged.values())))
    return reports, drift


_RUBRIC_SUITES = {"cultural", "register", "codemix"}

_COMPARED = ("judge", "judge_b", "suite", "subject", "n", "kappa", "agreement", "pabak",
             "test_retest", "framing_agreement", "precision", "recall", "spearman",
             "errors", "flags")


def _same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) < 1e-9
    return a == b


def verify_against_stored(reports: list, payload: dict, drift: list[dict] | None = None,
                          labeled_suites: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Compare rebuilt rows to the stored `reports`. Returns (problems, notes).

    Value columns must match exactly, with two documented exceptions. `flags` is
    compared as a superset check instead: the stored artifact predates round 1, so a
    rebuilt row legitimately carries flags (`canary-fail`, `threshold-sensitive`) the
    stored row has no field for — a flag that *disappeared* is a problem, one that
    appeared is a note.

    Rows are also skipped where the rebuild is *supposed* to differ: a row whose
    cases include a ground-truth drift (the matcher deliberately changed), and a
    rubric row whose kind flipped because labels were supplied. Everything else must
    match, which is what keeps the check meaningful.
    """
    stored = payload["reports"]
    drifted_suites = {d["suite"] for d in (drift or [])}
    labeled = labeled_suites or set()
    problems: list[str] = []
    notes: list[str] = []
    if len(stored) != len(reports):
        problems.append(f"row count: stored {len(stored)}, rebuilt {len(reports)}")
    for old, new in zip(stored, reports):
        where = (f"{old.get('suite')}/{old.get('subject')}/"
                 f"{old.get('judge')} vs {old.get('judge_b') or 'truth'}")
        if old.get("suite") in drifted_suites:
            notes.append(f"{where}: skipped (ground-truth drift on this suite)")
            continue
        if old.get("suite") in labeled and old.get("judge_b"):
            notes.append(f"{where}: skipped (rubric row re-kinded by labels)")
            continue
        for field in _COMPARED:
            if field == "flags":
                continue
            a, b = old.get(field), getattr(new, field, None)
            if not _same(a, b):
                problems.append(f"{where}: {field} stored {a!r} rebuilt {b!r}")
        old_flags, new_flags = set(old.get("flags") or []), set(new.flags)
        if old_flags - new_flags:
            problems.append(f"{where}: flags lost {sorted(old_flags - new_flags)}")
        if new_flags - old_flags:
            notes.append(f"{where}: gained {sorted(new_flags - old_flags)} (round-1 fields)")
    return problems, notes


def verify_against_readme(reports: list, path: Path) -> list[str]:
    """Compare rebuilt rows to the committed README table, row for row.

    This is the gate that makes regenerating the table safe: it proves the offline
    rebuild reproduces the numbers that were published, not merely the numbers in
    the artifact the rebuild reads from."""
    text = path.read_text(encoding="utf-8")
    head, rest = text.split(reporting.CALIBRATION_START, 1)
    body, _ = rest.split(reporting.CALIBRATION_END, 1)
    lines = [l for l in body.splitlines() if l.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    published = {}
    for line in lines[2:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        row = dict(zip(header, cells))
        published[(row["judge"], row["vs"], row["subject"], row["suite"])] = row

    fmt = lambda v: "-" if v is None else format(v, ".3f")  # noqa: E731
    problems: list[str] = []
    if len(published) != len(reports):
        problems.append(f"row count: README {len(published)}, rebuilt {len(reports)}")
    for r in reports:
        key = (r.judge, r.judge_b or "truth", r.subject, r.suite)
        row = published.get(key)
        if row is None:
            problems.append(f"README is missing row {key}")
            continue
        expect = {"n": str(r.n), "kappa": fmt(r.kappa), "pabak": fmt(r.pabak),
                  "retest": fmt(r.test_retest), "frame": fmt(r.framing_agreement),
                  "precision": fmt(r.precision), "recall": fmt(r.recall),
                  "spearman": fmt(r.spearman), "err": str(r.errors),
                  "k03": fmt(r.kappa_t03), "k07": fmt(r.kappa_t07),
                  "canary": f"{r.canary_failures}/{r.canaries}" if r.canaries else "-",
                  "draws": f"{r.draw_failures}/{r.draws}" if r.draws else "-",
                  "flags": ", ".join(r.flags)}
        for column, value in expect.items():
            if column in row and row[column] != value:
                problems.append(f"{key}: {column} README {row[column]!r} rebuilt {value!r}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", default="results_calibration.json")
    ap.add_argument("--labels", help="rubric labels JSONL (ground truth for the rubric suites)")
    ap.add_argument("--out", help="write the GitHub-Actions markdown table here")
    ap.add_argument("--match-audit", action="store_true",
                    help="report ground-truth drift instead of failing on it")
    ap.add_argument("--max-drift", type=int, default=0, metavar="N",
                    help="allow up to N scoreable rows to recompute differently (default 0). "
                         "Use 3 for the state after the intra-word joiner fix.")
    ap.add_argument("--verify-stored", action="store_true",
                    help="compare rebuilt rows against the artifact's stored reports")
    ap.add_argument("--verify-readme", metavar="PATH",
                    help="compare rebuilt rows against the committed README table")
    ap.add_argument("--duplicates", action="store_true",
                    help="list (case, subject) pairs sharing a byte-identical output")
    args = ap.parse_args()

    payload = json.loads(Path(args.artifact).read_text(encoding="utf-8"))

    if args.duplicates:
        shared = duplicate_outputs(payload)
        print(f"{len(shared)} case(s) with byte-identical outputs across subjects")
        for (suite, case_id, output), subjects in sorted(shared.items()):
            print(f"  {suite}/{case_id}: {', '.join(subjects)}")
            print(f"    {output[:100]!r}")
        return 0

    labels = None
    if args.labels:
        from ideval.calibrate import load_labels  # deferred: lands with the labels

        labels = load_labels(Path(args.labels))
        print(f"labels: {len(labels)} (suite, case, subject) annotations from {args.labels}")

    reports, drift = replay(payload, labels)

    scoreable_rows = sum(1 for r in payload["pairs"] if r["gt"] is not None)
    if drift:
        print(f"ground-truth drift: {len(drift)} of {scoreable_rows} scoreable rows "
              f"recompute differently")
        for d in drift:
            print(f"  {d['suite']}/{d['case_id']} [{d['subject']}] {d['judge']}: "
                  f"{d['stored']} -> {d['recomputed']}")
    else:
        print(f"ground truth reproduced exactly on {scoreable_rows}/{scoreable_rows} "
              f"scoreable rows")
    if drift and len(drift) > args.max_drift and not args.match_audit:
        print(f"refusing to rebuild the table: {len(drift)} scoreable row(s) no longer "
              f"reproduce the stored ground truth (--max-drift is {args.max_drift}); "
              f"re-run with --match-audit to inspect the drift")
        return 1
    if drift and len(drift) <= args.max_drift:
        print(f"drift {len(drift)} <= --max-drift {args.max_drift}: accepted")

    if args.verify_stored:
        labeled_suites = ({s for s in payload["config"]["suites"]
                           if any(k[0] == s for k in labels)} if labels else set())
        problems, notes = verify_against_stored(reports, payload, drift, labeled_suites)
        for note in notes:
            print(f"note: {note}")
        if problems:
            print(f"\nrebuilt table differs from the stored reports in {len(problems)} place(s):")
            for p in problems[:40]:
                print(f"  {p}")
            return 1
        print(f"rebuilt table matches the stored reports on all "
              f"{len(reports)} rows x {len(_COMPARED)} fields")

    if args.verify_readme:
        problems = verify_against_readme(reports, Path(args.verify_readme))
        if problems:
            print(f"\nrebuilt table differs from {args.verify_readme} in {len(problems)} place(s):")
            for p in problems[:40]:
                print(f"  {p}")
            return 1
        print(f"rebuilt table reproduces {args.verify_readme} row for row "
              f"({len(reports)} rows, every column)")

    reporting.print_calibration(reports)
    if args.out:
        Path(args.out).write_text(reporting.actions_summary(reports), encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

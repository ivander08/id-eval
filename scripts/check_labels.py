"""Offline label gate: no network, no API key, exits non-zero on any failure.

`annotations/rubric_labels.jsonl` is the ground truth for the rubric rows of the
README table and is consumed by `ideval calibrate --annotations` and by
`scripts/replay_calibration.py --labels`. `calibrate.load_labels` checks JSON
parseability and duplicate keys and nothing else — it accepts `"label": 0.7`. This
gate fails a PR that drops a row, puts a label off the 0.0/0.5/1.0 scale, leaves a
suite short of rectangular coverage, or lets a canary rise above 0.0.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideval.calibrate import load_labels  # noqa: E402
from ideval.schema import load_suite  # noqa: E402

RUBRIC_SUITES = ["cultural", "register", "codemix"]
VALID_LABELS = (0.0, 0.5, 1.0)
RATER = re.compile(r"^(?:draft|review):\S+$")
CANARY_PREFIX = "ADVERSARIAL"
FIELDS = {"suite", "case_id", "subject", "label", "rater", "note"}
LABELS_PATH = Path(__file__).resolve().parents[1] / "annotations" / "rubric_labels.jsonl"


def check(path: Path) -> tuple[list[str], list[str]]:
    """(failures, summary lines). Empty failures means the file is valid."""
    failures: list[str] = []
    summaries: list[str] = []

    if not path.exists():
        failures.append(f"{path}: not found")
        return failures, summaries

    rows: list[tuple[int, dict]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            failures.append(f"{path}:{lineno}: not a JSON object")
            continue
        if not isinstance(row, dict):
            failures.append(f"{path}:{lineno}: not a JSON object")
            continue
        rows.append((lineno, row))

    if not rows:
        failures.append(f"{path}: no data rows")

    cases_by_suite = {s: load_suite(s) for s in RUBRIC_SUITES}
    ids_by_suite = {s: {c.id for c in cases} for s, cases in cases_by_suite.items()}

    labels: dict[tuple[str, str, str], float] = {}
    first_line: dict[tuple[str, str, str], int] = {}

    for lineno, row in rows:
        keys = set(row)
        if FIELDS - keys:
            failures.append(f"{path}:{lineno}: missing keys {sorted(FIELDS - keys)}")
        if keys - FIELDS:
            failures.append(f"{path}:{lineno}: unexpected keys {sorted(keys - FIELDS)}")

        label = row.get("label")
        if isinstance(label, bool) or not isinstance(label, (int, float)) or float(label) not in VALID_LABELS:
            failures.append(f"{path}:{lineno}: label {label!r} is not one of 0.0, 0.5, 1.0")

        rater = row.get("rater")
        if not (isinstance(rater, str) and RATER.match(rater)):
            failures.append(f"{path}:{lineno}: rater {rater!r} does not match draft:<name> or review:<name>")

        note = row.get("note")
        if not isinstance(note, str):
            failures.append(f"{path}:{lineno}: note must be a string")

        subject = row.get("subject")
        if not (isinstance(subject, str) and subject.strip()):
            failures.append(f"{path}:{lineno}: subject must be a non-empty string")

        suite = row.get("suite")
        case_id = row.get("case_id")
        if not (isinstance(suite, str) and isinstance(case_id, str) and isinstance(subject, str)):
            continue

        key = (suite, case_id, subject)
        if key in first_line:
            failures.append(f"{path}:{lineno}: duplicate label for {key} (first at line {first_line[key]})")
        else:
            first_line[key] = lineno
            if isinstance(label, (int, float)) and not isinstance(label, bool):
                labels[key] = float(label)

        if suite not in RUBRIC_SUITES:
            failures.append(f"{path}:{lineno}: suite {suite!r} is not a rubric suite")
        elif case_id not in ids_by_suite[suite]:
            failures.append(f"{path}:{lineno}: {suite}/{case_id} is not a case in the suite files")

    for suite in RUBRIC_SUITES:
        cases = cases_by_suite[suite]
        subjects = sorted({key[2] for key in labels if key[0] == suite})
        if not subjects:
            failures.append(f"{suite}: no labels")
        for subject in subjects:
            missing = [c.id for c in cases if (suite, c.id, subject) not in labels]
            if missing:
                failures.append(f"{suite}: {len(missing)} case(s) with no label for subject "
                                f"{subject!r}: {missing[:5]}")
        for case in cases:
            if not (case.reference_note or "").startswith(CANARY_PREFIX):
                continue
            for subject in subjects:
                label = labels.get((suite, case.id, subject))
                if label is not None and label != 0.0:
                    failures.append(f"{suite}/{case.id}/{subject}: canary label is {label}, expected 0.0")

        summaries.append(f"{suite} {sum(1 for _, r in rows if r.get('suite') == suite)} labels / "
                         f"{len(cases)} cases x {len(subjects)} subjects")

    try:
        load_labels(path)
    except Exception as exc:
        failures.append(f"{path}: load_labels rejected the file: {exc}")

    return failures, summaries


def main() -> int:
    failures, summaries = check(LABELS_PATH)
    for line in summaries:
        print(line)

    if failures:
        print(f"\nFAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1

    canaries = sum(1 for s in RUBRIC_SUITES for c in load_suite(s)
                   if (c.reference_note or "").startswith(CANARY_PREFIX))
    print(f"\nOK: {len(load_labels(LABELS_PATH))} labels, {len(RUBRIC_SUITES)} suites, "
          f"{canaries} canaries, all labels in 0.0/0.5/1.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

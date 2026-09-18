"""Offline suite gate: no network, no API key, exits non-zero on any failure.

This is the CI regression gate. It fails a PR that drops a case, duplicates an
input (which double-counts one item in `n`), breaks a judge canary, or shrinks a
suite below `calibrate.LOW_N`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideval.calibrate import LOW_N  # noqa: E402
from ideval.schema import load_suite  # noqa: E402

SUITES = ["factual", "factual_indommlu", "factual_tydiqa", "cultural", "register", "codemix"]
SCOREABLE = {"factual", "factual_indommlu", "factual_tydiqa"}
CANARIES = {"cult-018": "cultural", "reg-018": "register", "cmx-018": "codemix"}


def main() -> int:
    failures: list[str] = []
    cases_by_suite = {}
    for name in SUITES:
        cases = load_suite(name)
        cases_by_suite[name] = cases

        if len(cases) < 32:
            failures.append(f"{name}: {len(cases)} cases, expected at least 32")
        if len(cases) < LOW_N:
            failures.append(f"{name}: {len(cases)} cases is below LOW_N={LOW_N} (row would be low-n)")

        ids = [c.id for c in cases]
        if len(set(ids)) != len(ids):
            failures.append(f"{name}: duplicate case ids: {sorted({i for i in ids if ids.count(i) > 1})}")
        inputs = [c.input for c in cases]
        if len(set(inputs)) != len(inputs):
            failures.append(f"{name}: {len(inputs) - len(set(inputs))} duplicate input(s) "
                            f"(a duplicate double-counts one item in n)")

        scoreable = sum(c.scoreable for c in cases)
        if name in SCOREABLE and scoreable != len(cases):
            failures.append(f"{name}: {scoreable}/{len(cases)} scoreable, expected all")
        if name not in SCOREABLE and scoreable != 0:
            failures.append(f"{name}: {scoreable} scoreable cases, expected 0 "
                            f"(rubric suites must take the inter-judge path)")

        print(f"{name} {len(cases)}/{scoreable}"
              f"{'' if name in SCOREABLE else ' (rubric)'}")

    for case_id, suite in CANARIES.items():
        case = next((c for c in cases_by_suite[suite] if c.id == case_id), None)
        if case is None:
            failures.append(f"{suite}: canary {case_id} is missing")
            continue
        if not case.judge_only:
            failures.append(f"{suite}/{case_id}: judge_only is not True")
        if not (case.reference_note or "").startswith("ADVERSARIAL"):
            failures.append(f"{suite}/{case_id}: reference_note does not start with ADVERSARIAL")

    if failures:
        print(f"\nFAIL ({len(failures)}):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"\nOK: {len(SUITES)} suites, {sum(len(c) for c in cases_by_suite.values())} cases, "
          f"3 canaries, all clearing low-n (n >= {LOW_N})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

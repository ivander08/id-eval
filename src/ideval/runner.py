from __future__ import annotations

import json
import re
from pathlib import Path

from rich.progress import track

from .adapters import chat, make_client
from .metrics.base import SCORE_CONTRACT, parse_verdict
from .metrics import rubric_for
from .schema import EvalResult, TestCase, load_suite

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_CHOICE = re.compile(r"(?:^|\W)([A-E])(?=[\W_]|$)")


def _normalize(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace (SQuAD-style)."""
    return _SPACES.sub(" ", _PUNCT.sub(" ", text.lower())).strip()


def _match_exact(output: str, expected: str) -> float:
    """Normalized containment: the expected answer must appear in the output."""
    norm_expected = _normalize(expected)
    if not norm_expected:
        return 0.0
    return float(norm_expected in _normalize(output))


def _match_choice(output: str, expected: str) -> float:
    """Multiple-choice: last standalone uppercase letter A-E wins (case-sensitive:
    a bare lowercase 'a' in Indonesian text is a word, not an answer)."""
    letters = _CHOICE.findall(output)
    return float(bool(letters) and letters[-1] == expected.strip().upper())


def generate_outputs(cases: list[TestCase], model: str) -> list[EvalResult]:
    """Subject-model outputs + ground-truth scores. No judge calls."""
    needs_subject = any(not c.judge_only for c in cases)
    subject_client = subject_model_id = None
    if needs_subject:
        subject_client, subject_model_id = make_client(model)

    suite = cases[0].suite if cases else "?"
    results: list[EvalResult] = []
    for case in track(cases, description=f"{suite} x {model}"):
        if case.judge_only:
            results.append(EvalResult(case_id=case.id, suite=case.suite, model="(embedded)", output=case.input))
            continue
        try:
            output = chat(subject_client, subject_model_id, case.input, case.context)
            result = EvalResult(case_id=case.id, suite=case.suite, model=model, output=output)
        except Exception as e:  # noqa: BLE001 - record and continue
            results.append(EvalResult(case_id=case.id, suite=case.suite, model=model, output="", error=str(e)))
            continue

        if case.scoreable:
            if case.ground_truth_type == "choice":
                result.score = _match_choice(output, case.expected or "")
            else:
                result.score = _match_exact(output, case.expected or "")
        results.append(result)
    return results


def score_with_judge(cases: list[TestCase], results: list[EvalResult], judge_model: str) -> int:
    """Fill judge_score (scoreable) or score (rubric) on `results`. Returns the
    number of cases the judge failed to score.

    Every case is reset before scoring, so a judge that fails leaves the field
    unset instead of inheriting the previous judge's verdict."""
    client, model_id = make_client(judge_model)
    errors = 0
    for case, result in zip(cases, results):
        if case.scoreable:
            result.judge_score = None
        else:
            result.score = None
        if result.error:
            errors += 1
            continue
        verdict = _judge(client, model_id, case, result.output)
        if verdict is None:
            errors += 1
            continue
        if case.scoreable:
            result.judge_score = verdict.score
        else:
            result.score = verdict.score
    return errors


def run_suite(suite: str, model: str, judge_model: str | None = None,
              limit: int | None = None, out: Path | None = None) -> list[EvalResult]:
    cases = load_suite(suite)
    if limit:
        cases = cases[:limit]

    results = generate_outputs(cases, model)
    if judge_model:
        score_with_judge(cases, results, judge_model)
    else:
        for case, result in zip(cases, results):
            if case.judge_only:
                result.error = "judge_only case requires --judge"

    if out:
        payload = {"suite": suite, "model": model, "judge": judge_model,
                   "results": [r.model_dump() for r in results]}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def _judge(client, model_id: str, case: TestCase, output: str):
    rubric = rubric_for(case.suite).format(reference=case.expected or "-", contract=SCORE_CONTRACT)
    prompt = f"Context: {case.context or '-'}\n\nPrompt: {case.input}\n\nResponse to evaluate:\n{output}\n\n{rubric}"
    try:
        raw = chat(client, model_id, prompt)
    except Exception:  # noqa: BLE001
        return None
    return parse_verdict(raw)

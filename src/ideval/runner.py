from __future__ import annotations

import json
import re
from pathlib import Path

from rich.progress import track

from .adapters import chat, make_client
from .metrics.base import SCORE_CONTRACT, JudgeVerdict, parse_verdict
from .metrics import rubric_for
from .schema import EvalResult, TestCase, load_suite

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACES = re.compile(r"\s+")
_CHOICE = re.compile(r"(?:^|\W)([A-E])(?=[\W_]|$)")

_SUPERSCRIPT = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")
_UNITS = [
    (re.compile(r"\bsquare\s+kilomet(?:er|re)s?\b"), "km2"),
    (re.compile(r"\bkilomet(?:er|re)s?\s+(?:persegi|kuadrat)\b"), "km2"),
    (re.compile(r"\bkm\s*2\b"), "km2"),
    (re.compile(r"\bhect?ares?\b"), "ha"),
    (re.compile(r"\bhektare?\b"), "ha"),
]


def _normalize(text: str) -> str:
    """Lowercase, canonicalize superscripts and units, strip punctuation,
    collapse whitespace (SQuAD-style plus unit canonicalization)."""
    text = text.lower().translate(_SUPERSCRIPT)
    text = _PUNCT.sub(" ", text)
    text = _SPACES.sub(" ", text)
    for pattern, replacement in _UNITS:
        text = pattern.sub(replacement, text)
    return _SPACES.sub(" ", text).strip()


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


def score_with_judge(cases: list[TestCase], results: list[EvalResult], judge_model: str,
                     repeats: int = 1) -> int:
    """Fill judge_score (scoreable) or score (rubric) on `results`. Returns the
    number of cases the judge failed to score on every draw.

    Every case is reset before scoring, so a judge that fails leaves the field
    unset instead of inheriting the previous judge's verdict.

    With repeats > 1 each case is judged `repeats` times, alternating prompt
    framing (variant = draw index % 2). `judge_score` is the first successful
    draw; `judge_repeats` holds them all. A case counts as an error only when
    every draw failed, so `n + errors` still equals the case count."""
    client, model_id = make_client(judge_model)
    errors = 0
    for case, result in zip(cases, results):
        if case.scoreable:
            result.judge_score = None
        else:
            result.score = None
        result.judge_reason = None
        result.judge_raw = None
        result.judge_repeats = []
        if result.error:
            errors += 1
            continue
        scores: list[float] = []
        last_raw = ""
        for draw in range(repeats):
            verdict, raw = _judge(client, model_id, case, result.output, variant=draw % 2)
            last_raw = raw
            if verdict is None:
                continue
            scores.append(verdict.score)
            if result.judge_reason is None:
                result.judge_reason = verdict.reason
        if not scores:
            result.judge_raw = last_raw
            errors += 1
            continue
        result.judge_repeats = scores
        if case.scoreable:
            result.judge_score = scores[0]
        else:
            result.score = scores[0]
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


def _judge(client, model_id: str, case: TestCase, output: str,
           variant: int = 0) -> tuple[JudgeVerdict | None, str]:
    """(verdict, raw). raw == "" means the API call raised; raw != "" with a None
    verdict means the response did not parse.

    variant 0 puts the rubric after the response; variant 1 puts it before, which
    is the pointwise analogue of position bias: same content, different framing."""
    rubric = rubric_for(case.suite).format(reference=case.expected or "-", contract=SCORE_CONTRACT)
    head = f"Context: {case.context or '-'}\n\nPrompt: {case.input}\n\nResponse to evaluate:\n{output}"
    prompt = f"{head}\n\n{rubric}" if variant == 0 else f"{rubric}\n\n{head}"
    try:
        raw = chat(client, model_id, prompt)
    except Exception:  # noqa: BLE001
        return None, ""
    return parse_verdict(raw), raw

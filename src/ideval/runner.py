from __future__ import annotations

import json
import re
from pathlib import Path

from rich.progress import track

from .adapters import chat, make_client
from .metrics.base import (PAIR_CONTRACT, SCORE_CONTRACT, JudgeVerdict, PairVerdict,
                           parse_pair_verdict, parse_verdict)
from .metrics import rubric_for
from .schema import EvalResult, TestCase, load_suite

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_JOINER = re.compile(r"(?<=\w)['\u2019\-](?=\w)")
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
    collapse whitespace (SQuAD-style plus unit canonicalization).

    Intra-word joiners (apostrophes and hyphens between word characters) are
    deleted before punctuation stripping, so `Al-Qur'an` and `Alquran` normalize
    to the same token instead of splitting into `al qur an`."""
    text = text.lower().translate(_SUPERSCRIPT)
    text = _JOINER.sub("", text)
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
                     repeats: int = 1, backend: str = "native") -> int:
    """Fill judge_score (scoreable) or score (rubric) on `results`. Returns the
    number of cases the judge failed to score on every draw.

    Every case is reset before scoring, so a judge that fails leaves the field
    unset instead of inheriting the previous judge's verdict.

    With repeats > 1 each case is judged `repeats` times, alternating prompt
    framing (variant = draw index % 2). `judge_score` is the first successful
    draw; `judge_repeats` holds them all. A case counts as an error only when
    every draw failed, so `n + errors` still equals the case count.

    `backend` selects the judge implementation: "native" (the JSON-contract
    prompt above) or "deepeval" (GEval via `metrics.deepeval_backend`)."""
    if backend == "deepeval":
        from .metrics.deepeval_backend import judge_case, make_judge
        judge = make_judge(judge_model)
        client = model_id = None
    else:
        client, model_id = make_client(judge_model)
        judge = None
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
            if judge is not None:
                verdict, raw = judge_case(judge, case, result.output, variant=draw % 2)
            else:
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
              limit: int | None = None, out: Path | None = None,
              judge_backend: str = "native") -> list[EvalResult]:
    cases = load_suite(suite)
    if limit:
        cases = cases[:limit]

    results = generate_outputs(cases, model)
    if judge_model:
        score_with_judge(cases, results, judge_model, backend=judge_backend)
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


def _judge_pair(client, model_id: str, case: TestCase, output_a: str, output_b: str,
                variant: int = 0, framing: int = 0) -> tuple[PairVerdict | None, str]:
    """(verdict, raw), mirroring `_judge`'s failure contract. `variant` controls
    which response is presented as A: variant 0 -> (output_a, output_b), variant 1
    -> (output_b, output_a). The caller compares the two orders to detect position
    bias, so this function must not itself correct for position.

    `framing` is the second, independent axis: 0 puts the rubric after the two
    responses, 1 before them, exactly as `_judge`'s variant does for one response.
    Order and framing are separate arguments because a caller measuring position
    bias has to hold the order fixed while framing alternates — folding them into
    one argument would swap the responses when the caller meant to move the rubric.

    This is the pairwise protocol §8.2 said was untested. It is a different
    experiment from the pointwise `frame` column: that one moves the rubric around
    a single response, this one swaps two responses under a fixed rubric."""
    rubric = rubric_for(case.suite).format(reference=case.expected or "-", contract=PAIR_CONTRACT)
    first, second = (output_a, output_b) if variant % 2 == 0 else (output_b, output_a)
    head = (f"Context: {case.context or '-'}\n\nPrompt: {case.input}\n\n"
            f"Response A:\n{first}\n\nResponse B:\n{second}")
    prompt = f"{head}\n\n{rubric}" if framing % 2 == 0 else f"{rubric}\n\n{head}"
    try:
        raw = chat(client, model_id, prompt)
    except Exception:  # noqa: BLE001
        return None, ""
    return parse_pair_verdict(raw), raw

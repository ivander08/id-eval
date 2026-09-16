from __future__ import annotations

import json
import re
from pathlib import Path

from rich.progress import track

from .adapters import chat, make_client
from .metrics.base import SCORE_CONTRACT, parse_verdict
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


def run_suite(suite: str, model: str, judge_model: str | None = None,
              limit: int | None = None, out: Path | None = None) -> list[EvalResult]:
    cases = load_suite(suite)
    if limit:
        cases = cases[:limit]

    judge_client = judge_model_id = None
    if judge_model:
        judge_client, judge_model_id = make_client(judge_model)

    needs_subject = any(not c.judge_only for c in cases)
    subject_client = subject_model_id = None
    if needs_subject:
        subject_client, subject_model_id = make_client(model)

    results: list[EvalResult] = []
    for case in track(cases, description=f"{suite} x {model}"):
        try:
            if case.judge_only:
                result = EvalResult(case_id=case.id, suite=suite, model="(embedded)", output=case.input)
                if judge_client:
                    verdict = _judge(judge_client, judge_model_id, case, case.input)
                    result.score = verdict.score if verdict else None
                else:
                    result.error = "judge_only case requires --judge"
                results.append(result)
                continue

            output = chat(subject_client, subject_model_id, case.input, case.context)
            result = EvalResult(case_id=case.id, suite=suite, model=model, output=output)
        except Exception as e:  # noqa: BLE001 - record and continue
            results.append(EvalResult(case_id=case.id, suite=suite, model=model, output="", error=str(e)))
            continue

        if case.scoreable:
            if case.ground_truth_type == "choice":
                result.score = _match_choice(output, case.expected or "")
            else:
                result.score = _match_exact(output, case.expected or "")
        elif judge_client:
            verdict = _judge(judge_client, judge_model_id, case, output)
            result.score = verdict.score if verdict else None
        results.append(result)

    if out:
        payload = {"suite": suite, "model": model, "judge": judge_model,
                   "results": [r.model_dump() for r in results]}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def _judge(client, model_id: str, case: TestCase, output: str):
    prompt = f"Context: {case.context or '-'}\n\nPrompt: {case.input}\n\nResponse to evaluate:\n{output}\n\n{SCORE_CONTRACT}"
    try:
        raw = chat(client, model_id, prompt)
    except Exception:  # noqa: BLE001
        return None
    return parse_verdict(raw)

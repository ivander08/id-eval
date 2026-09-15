from __future__ import annotations

import json
from pathlib import Path

from rich.progress import track

from .adapters import chat, make_client
from .metrics.base import SCORE_CONTRACT, parse_verdict
from .schema import EvalResult, TestCase, load_suite


def run_suite(suite: str, model: str, judge_model: str | None = None,
              limit: int | None = None, out: Path | None = None) -> list[EvalResult]:
    cases = load_suite(suite)
    if limit:
        cases = cases[:limit]

    client, model_id = make_client(model)
    judge_client = judge_model_id = None
    if judge_model:
        judge_client, judge_model_id = make_client(judge_model)

    results: list[EvalResult] = []
    for case in track(cases, description=f"{suite} x {model}"):
        try:
            output = chat(client, model_id, case.input, case.context)
            result = EvalResult(case_id=case.id, suite=suite, model=model, output=output)
        except Exception as e:  # noqa: BLE001 - record and continue
            results.append(EvalResult(case_id=case.id, suite=suite, model=model, output="", error=str(e)))
            continue

        if case.scoreable:
            result.score = float(output.strip().lower() == (case.expected or "").strip().lower())
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

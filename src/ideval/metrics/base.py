"""Rubric base for id-eval metrics.

M0 note: judge scoring is implemented with plain chat-completions + a strict
JSON score contract and tolerant parser. deepeval GEval integration lands in
M1 (metric classes will subclass GEval there); the JSON contract and parser
are already final so calibration code is stable from day one.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel


class JudgeVerdict(BaseModel):
    score: float  # 0.0 .. 1.0
    reason: str = ""


SCORE_CONTRACT = (
    'Reply with ONLY a JSON object: {"score": <float 0.0-1.0>, "reason": "<max 2 sentences>"}\n'
    "Do NOT reward length, hedging, or disclaimers — judge content only."
)


def parse_verdict(text: str) -> JudgeVerdict | None:
    """Tolerant parser: finds the first JSON object with a numeric score."""
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    score = data.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return JudgeVerdict(score=max(0.0, min(1.0, float(score))), reason=str(data.get("reason", "")))

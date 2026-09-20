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


PAIR_CONTRACT = (
    'Reply with ONLY a JSON object: {"winner": "A" or "B", "reason": "<max 2 sentences>"}\n'
    "Do NOT reward length, hedging, or disclaimers — judge which response better satisfies the rubric."
)


class PairVerdict(BaseModel):
    winner: str  # "A" or "B"
    reason: str = ""


def parse_pair_verdict(text: str) -> PairVerdict | None:
    """Tolerant parser for the pairwise contract. None when no JSON object with
    winner in {A, B} is present.

    Same shape as `parse_verdict` (first flat JSON object, tolerant of surrounding
    prose) but keyed on `winner`. Anything that is not exactly "A" or "B" after
    `.strip().upper()` is rejected, so a judge that hedges with "neither" or names
    a response's content fails rather than being coerced into a position."""
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    winner = data.get("winner")
    if not isinstance(winner, str) or winner.strip().upper() not in ("A", "B"):
        return None
    return PairVerdict(winner=winner.strip().upper(), reason=str(data.get("reason", "")))

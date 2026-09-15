from .base import JudgeVerdict, SCORE_CONTRACT, parse_verdict

RUBRIC = """You are evaluating an AI assistant's response to an INDONESIAN-ENGLISH
CODE-MIXED prompt (e.g. Bahasa + English tech/business vocabulary, "gimme
insight-nya dong"). Score 0.0 to 1.0.

Fail (<= 0.3) if the model ignores the Indonesian part of the prompt,
misunderstands the mixed intent, or forces pure-English or pure-Indonesian
when a mixed reply is clearly appropriate.

Pass (>= 0.7) if it handles both languages correctly and answers the
actual question.

When in doubt, use the midpoint. {contract}"""

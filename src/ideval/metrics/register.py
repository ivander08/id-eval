from .base import JudgeVerdict, SCORE_CONTRACT, parse_verdict

RUBRIC = """You are evaluating whether an AI assistant's response matches the REQUIRED
INDONESIAN LANGUAGE REGISTER. Score 0.0 to 1.0.

Registers:
- formal (baku): government, legal, academic contexts
- santai (casual): friendly conversation, lifestyle topics
- jaksel (Jakarta-English code-mixed): startup/social-media voice

Fail (<= 0.3) if the register is wrong for the context, code-switching is
incoherent, or the mix of Indonesian/English is jarring.

Pass (>= 0.7) if register matches the stated context and reads naturally.

When in doubt, use the midpoint. {contract}"""

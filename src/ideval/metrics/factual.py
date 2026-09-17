"""Reference-aware factual rubric: the judge sees the ground-truth answer, so it
can grade correctness instead of plausibility."""

RUBRIC = """You are evaluating whether an AI assistant's answer is factually CORRECT
about Indonesia. Score 0.0 (wrong) to 1.0 (correct).

Reference answer: {reference}

Score 1.0 if the response states the reference answer or an unambiguous
equivalent. Score 0.0 if it states something different, contradicts the
reference, or answers a different question. Partial credit only when the
reference answer appears alongside correct extra detail.

Do NOT reward fluency, confidence, or length. {contract}"""

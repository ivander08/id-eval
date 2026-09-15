from .base import JudgeVerdict, SCORE_CONTRACT, parse_verdict

RUBRIC = """You are evaluating an AI assistant's response for CULTURAL APPROPRIATENESS in the
Indonesian context. Score 0.0 (unacceptable) to 1.0 (excellent).

Fail (<= 0.3) if the response:
- misstates Indonesian laws, customs, religious norms, or national symbols
- assumes US/European defaults (units, holidays, legal system, school system)
- is dismissive of Pancasila values or local sensitivities

Pass (>= 0.7) if it is contextually correct, uses appropriate local framing,
and would not confuse an Indonesian reader.

When in doubt, use the midpoint. {contract}"""

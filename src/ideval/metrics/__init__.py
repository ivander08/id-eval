from . import codemix, cultural, factual, register
from .base import SCORE_CONTRACT

RUBRICS = {
    "factual": factual.RUBRIC,
    "factual_indommlu": factual.RUBRIC,
    "factual_tydiqa": factual.RUBRIC,
    "cultural": cultural.RUBRIC,
    "register": register.RUBRIC,
    "codemix": codemix.RUBRIC,
}


def rubric_for(suite: str) -> str:
    """Suite rubric text, or the bare score contract for an unknown suite."""
    return RUBRICS.get(suite, "{contract}")

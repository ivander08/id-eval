from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

GroundTruthType = Literal["exact", "choice", "rubric"]

SUITES_DIR = Path(__file__).resolve().parents[2] / "suites"


class TestCase(BaseModel):
    id: str
    suite: str
    input: str
    context: str | None = None
    expected: str | None = None
    ground_truth_type: GroundTruthType
    source: str = "hand-curated"
    reference_note: str | None = None
    judge_only: bool = False  # score the embedded response directly; skip the subject model

    @property
    def scoreable(self) -> bool:
        return self.ground_truth_type in ("exact", "choice") and self.expected is not None


class EvalResult(BaseModel):
    case_id: str
    suite: str
    model: str
    output: str
    score: float | None = None  # 0..1 for exact match; None = needs judge (rubric)
    error: str | None = None


class SuiteSummary(BaseModel):
    name: str
    path: Path
    count: int
    scoreable: int
    rubric: int


def load_suite(name: str, suites_dir: Path = SUITES_DIR) -> list[TestCase]:
    path = suites_dir / f"{name}.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Suite not found: {path}")
    cases = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        cases.append(TestCase.model_validate_json(line))
    return cases


def suite_summaries(suites_dir: Path = SUITES_DIR) -> list[SuiteSummary]:
    summaries = []
    for path in sorted(suites_dir.glob("*.jsonl")):
        cases = [TestCase.model_validate_json(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        summaries.append(SuiteSummary(
            name=path.stem,
            path=path,
            count=len(cases),
            scoreable=sum(c.scoreable for c in cases),
            rubric=sum(not c.scoreable for c in cases),
        ))
    return summaries

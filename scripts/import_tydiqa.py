"""Import TyDiQA-GoldP Indonesian (khalidalt/tydiqa-goldp, Apache-2.0) as exact cases.

Expects data/tydiqa-id-dev.jsonl (downloaded by scripts/download_data.py).
Answer = gold span; scoring uses containment matching so spans embedded in
generated sentences count. source=google-research-datasets/tydiqa.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA_PATH = REPO / "data" / "tydiqa-id-dev.jsonl"
OUT_PATH = REPO / "suites" / "factual_tydiqa.jsonl"
TARGET = 40
MIN_ANSWER_LEN = 4   # skip 1-3 char spans: containment match too loose
MAX_ANSWER_LEN = 60  # skip paragraph-span answers: containment match too strict
MAX_CONTEXT_LEN = 1200


def main() -> None:
    if not DATA_PATH.exists():
        sys.exit(f"missing {DATA_PATH}; run scripts/download_data.py first")

    rows = []
    for line in DATA_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))

    rng = random.Random(42)
    rng.shuffle(rows)

    seen_questions: set[str] = set()
    cases = []
    for row in rows:
        if len(cases) >= TARGET:
            break
        question = row["question_text"].strip()
        answers = row.get("answers") or []
        if not question or question.lower() in seen_questions or not answers:
            continue
        # shortest gold answer: least chance of spanning off-topic text;
        # normalize whitespace and drop spans with replacement chars
        # (byte-offset slicing in the source can cut mid-character)
        answer = " ".join(min((a["text"] for a in answers), key=len).split())
        if "\ufffd" in answer:
            continue
        if not (MIN_ANSWER_LEN <= len(answer) <= MAX_ANSWER_LEN):
            continue
        context = row["passage_text"].strip()
        if len(context) > MAX_CONTEXT_LEN:
            context = context[:MAX_CONTEXT_LEN]
        seen_questions.add(question.lower())
        cases.append({
            "id": f"tydiqa-{len(cases):03d}",
            "suite": "factual_tydiqa",
            "input": question,
            "context": context,
            "expected": answer,
            "ground_truth_type": "exact",
            "source": "google-research-datasets/tydiqa",
        })

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases -> {OUT_PATH}")


if __name__ == "__main__":
    main()

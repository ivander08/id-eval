"""Import IndoMMLU (indolem/IndoMMLU, MIT) into suites/factual.jsonl as choice cases.

Stratified sample across subjects; expects data/IndoMMLU.csv (downloaded by
scripts/download_data.py). Output cases have ground_truth_type=choice and
source=indolem/IndoMMLU.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSV_PATH = REPO / "data" / "IndoMMLU.csv"
OUT_PATH = REPO / "suites" / "factual_indommlu.jsonl"
TARGET_PER_SUBJECT = 4
MAX_CASES = 80

PROMPT = (
    "Jawab pertanyaan pilihan ganda berikut. Balas HURUF jawaban yang benar "
    "(A/B/C/D/E) saja, tanpa penjelasan.\n\n{soal}\n\n{opsi}"
)


def main() -> None:
    if not CSV_PATH.exists():
        sys.exit(f"missing {CSV_PATH}; run scripts/download_data.py first")

    with CSV_PATH.open(encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("is_for_fewshot") == "0"]

    rng = random.Random(42)  # ponytail: fixed seed, reproducible suite
    by_subject: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        soal, opsi, kunci = row["soal"].strip(), row["jawaban"].strip(), row["kunci"].strip().upper()
        # keep only well-formed MC rows: options + a valid letter key
        if soal and opsi and kunci in "ABCDE" and len(opsi.splitlines()) >= 2:
            by_subject[row["subject"].strip()].append(row)

    subjects = sorted(by_subject)
    picked: list[dict] = []
    while len(picked) < MAX_CASES:
        added = False
        for subject in subjects:
            if len(picked) >= MAX_CASES:
                break
            pool = by_subject[subject]
            if pool:
                picked.append(pool.pop(rng.randrange(len(pool))))
                added = True
        if not added:  # all pools exhausted
            break

    # dedupe identical questions (CSV has repeats across exam years)
    seen: set[str] = set()
    cases = []
    for row in picked:
        q = row["soal"].strip()
        if q in seen:
            continue
        seen.add(q)
        cases.append({
            "id": f"mmlu-{row['id']}",
            "suite": "factual_indommlu",
            "input": PROMPT.format(soal=q, opsi=row["jawaban"].strip()),
            "expected": row["kunci"].strip().upper(),
            "ground_truth_type": "choice",
            "source": f"indolem/IndoMMLU;{row['subject']};{row['level']}",
        })

    with OUT_PATH.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"wrote {len(cases)} cases -> {OUT_PATH}")


if __name__ == "__main__":
    main()

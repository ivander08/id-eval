"""Bounded parity sample: judge the SAME subject outputs with both backends.

The `calibrate` CLI regenerates subject outputs on every run and `adapters.chat`
deliberately pins no temperature (design-notes §7), so two `calibrate` runs are
not comparable — they judge different text. This holds the outputs fixed and
varies only the judge implementation, which is the actual question.

Usage: python scripts/parity_sample.py <suite> [limit]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ideval.metrics.deepeval_backend import judge_case, make_judge  # noqa: E402
from ideval.runner import _judge, generate_outputs  # noqa: E402
from ideval.schema import load_suite  # noqa: E402

SUITE = sys.argv[1] if len(sys.argv) > 1 else "factual"
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 16
SUBJECT = "kenari/qwen3-8-flash"
JUDGE = "kenari/deepseek-v4-1-flash"
REPEATS = 2

cases = load_suite(SUITE)[:LIMIT]
results = generate_outputs(cases, SUBJECT)
outputs = {r.case_id: r.output for r in results}

from ideval.adapters import make_client  # noqa: E402

client, model_id = make_client(JUDGE)
repo_judge = make_judge(JUDGE)

rows = []
for case in cases:
    out = outputs[case.id]
    if not out:
        continue
    draws = {}
    reasons = {}
    for name, fn in (("native", lambda v: _judge(client, model_id, case, out, variant=v)),
                     ("deepeval", lambda v: judge_case(repo_judge, case, out, variant=v))):
        verdicts = [fn(d % 2) for d in range(REPEATS)]
        scores = [v.score for v, _ in verdicts if v is not None]
        draws[name] = scores
        reasons[name] = next((v.reason for v, _ in verdicts if v is not None), "")
    rows.append({"suite": SUITE, "case_id": case.id, "expected": case.expected,
                 "output": out, "native": draws["native"], "deepeval": draws["deepeval"],
                 "native_reason": reasons["native"], "deepeval_reason": reasons["deepeval"]})

paired = [r for r in rows if r["native"] and r["deepeval"]]
agree = sum(1 for r in paired if (r["native"][0] >= 0.5) == (r["deepeval"][0] >= 0.5))
print(f"\n{SUITE}: {len(rows)} judged, {len(paired)} paired, "
      f"binarized agreement {agree}/{len(paired)} = {agree / len(paired):.3f}")
print(f"native drew {sum(len(r['native']) for r in rows)} verdicts, "
      f"deepeval drew {sum(len(r['deepeval']) for r in rows)}")
for r in paired:
    a, b = r["native"][0], r["deepeval"][0]
    mark = " " if (a >= 0.5) == (b >= 0.5) else "X"
    print(f" {mark} {r['case_id']:10s} native={a:<5} deepeval={b:<5} "
          f"expected={str(r['expected'])[:18]:18s} out={(r['output'] or '')[:38]!r}")
    if mark == "X":
        print(f"     native reason:   {r['native_reason'][:200]!r}")
        print(f"     deepeval reason: {r['deepeval_reason'][:200]!r}")

Path(f"results_parity_{SUITE}.json").write_text(
    json.dumps({"suite": SUITE, "subject": SUBJECT, "judge": JUDGE, "rows": rows},
               ensure_ascii=False, indent=2), encoding="utf-8")

import os
import time

if not os.environ.get("OPENAI_API_KEY"):
    raise SystemExit("set OPENAI_API_KEY before running this probe")

t0 = time.time()
from ideval.runner import run_suite

print(f"import: {time.time()-t0:.1f}s", flush=True)
t0 = time.time()
results = run_suite("cultural", "ollama/qwen2.5:1.5b", judge_model="kenari/deepseek-v4-1-flash", limit=2)
print(f"run: {time.time()-t0:.1f}s", flush=True)
for r in results:
    print(r.case_id, r.score, (r.error or "")[:80], "|", r.output[:60].replace("\n", " "))

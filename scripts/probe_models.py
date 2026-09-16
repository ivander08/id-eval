import os
import time

os.environ.setdefault("OPENAI_API_KEY", "kn-4e9a9cf2d05e3dd236201043169ff89cea07d32d3954db95")

from openai import OpenAI

c = OpenAI(base_url="https://kenari.id/v1", api_key=os.environ["OPENAI_API_KEY"], timeout=60)

for model in ["gemini-2-5-flash", "deepseek-v4-flash", "gpt-5-4-mini", "glm-5-3-flash", "qwen3-8-flash"]:
    t = time.time()
    try:
        r = c.chat.completions.create(model=model, messages=[{"role": "user", "content": "say OK"}])
        print(f"{model}: OK {time.time()-t:.1f}s -> {r.choices[0].message.content[:30]!r}", flush=True)
    except Exception as e:
        print(f"{model}: FAIL {time.time()-t:.1f}s {str(e)[:80]}", flush=True)

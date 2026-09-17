import os
import time

from openai import OpenAI

t0 = time.time()
try:
    c = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama", timeout=60)
    r = c.chat.completions.create(model="qwen2.5:1.5b",
                                  messages=[{"role": "user", "content": "Jawab satu kata: apa ibu kota Jawa Barat?"}])
    print(f"ollama OK {time.time()-t0:.1f}s:", r.choices[0].message.content[:60])
except Exception as e:
    print(f"ollama FAIL {time.time()-t0:.1f}s:", str(e)[:150])

t0 = time.time()
try:
    c = OpenAI(base_url="https://kenari.id/v1", api_key=os.environ["OPENAI_API_KEY"], timeout=120)
    r = c.chat.completions.create(model="deepseek-v4-1-flash",
                                  messages=[{"role": "user", "content": 'Reply with ONLY JSON {"score": 0.0-1.0, "reason": "..."} evaluating: Q: Apa ibu kota Jawa Barat? Response: "Bandung adalah ibu kotanya."'}])
    print(f"kenari OK {time.time()-t0:.1f}s:", r.choices[0].message.content[:120])
except Exception as e:
    print(f"kenari FAIL {time.time()-t0:.1f}s:", str(e)[:150])

"""One adapter for every OpenAI-compatible endpoint: OpenAI, OpenRouter,
proxies, Gemini-compat, Ollama (http://localhost:11434/v1)."""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI


@dataclass
class ModelRef:
    """model identifier like `openrouter/qwen/qwen3-4b` or `ollama/qwen2.5:1.5b`."""

    raw: str

    @property
    def provider(self) -> str:
        return self.raw.split("/", 1)[0]

    @property
    def model_id(self) -> str:
        return self.raw.split("/", 1)[1] if "/" in self.raw else self.raw

    def base_url(self) -> str | None:
        return {
            "ollama": "http://localhost:11434/v1",
            "openrouter": "https://openrouter.ai/api/v1",
            "kenari": "https://kenari.id/v1",
        }.get(self.provider)


def make_client(model: str, api_key_env: str = "OPENAI_API_KEY") -> tuple[OpenAI, str]:
    ref = ModelRef(model)
    # ollama needs no real key; other providers must get one (env or a placeholder
    # when the provider's base_url handles auth, e.g. proxies with keyless tiers)
    if ref.provider == "ollama":
        api_key = "ollama"
    else:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"provider '{ref.provider}' requires {api_key_env} to be set "
                f"(model: {model})")
    base_url = ref.base_url() or os.environ.get("OPENAI_BASE_URL")  # ponytail: generic proxy support
    client = OpenAI(base_url=base_url, api_key=api_key)
    return client, ref.model_id


def chat(client: OpenAI, model_id: str, prompt: str, context: str | None = None) -> str:
    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": prompt})
    # ponytail: no temperature pinning — temp=0 stalls qwen2.5 on Ollama 0.34;
    # per-provider defaults are fine for eval reproducibility at this scale
    resp = client.chat.completions.create(model=model_id, messages=messages)
    return resp.choices[0].message.content or ""

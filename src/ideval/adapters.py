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
        }.get(self.provider)


def make_client(model: str, api_key_env: str = "OPENAI_API_KEY") -> tuple[OpenAI, str]:
    ref = ModelRef(model)
    api_key = os.environ.get(api_key_env, "ollama")
    client = OpenAI(base_url=ref.base_url(), api_key=api_key)
    return client, ref.model_id


def chat(client: OpenAI, model_id: str, prompt: str, context: str | None = None) -> str:
    messages = []
    if context:
        messages.append({"role": "system", "content": context})
    messages.append({"role": "user", "content": prompt})
    resp = client.chat.completions.create(model=model_id, messages=messages, temperature=0)
    return resp.choices[0].message.content or ""

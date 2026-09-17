# id-eval

Indonesian LLM evaluation toolkit: curated suites, calibrated LLM-as-judge, CI-ready.

## Status

Work in progress. Milestones:

- [x] M0 — scaffold, CLI, schema, suites seeds, tests
- [ ] M1 — deepeval metric classes + runner hardening + ~200 curated cases
- [x] M2 — `ideval calibrate`: judge agreement study (Cohen's kappa, Spearman)
- [ ] M3 — CI eval job, published calibration table, blog post
- [ ] M4 — PyPI release, upstream deepeval contribution

## Install

```bash
pip install -e ".[dev]"   # dev install
```

## Usage

```bash
ideval list-suites
ideval run factual --model ollama/qwen2.5:1.5b --judge openrouter/openai/gpt-4o-mini
```

Models follow `provider/model-id` syntax. Providers: `openai` (any OpenAI-compatible
endpoint via `OPENAI_API_KEY`/`OPENAI_BASE_URL`), `openrouter`, `ollama`.

## Suites

| suite | what it measures | ground truth |
|---|---|---|
| factual | Indonesian factual QA (IndoMMLU-derived + seeds) | exact match |
| cultural | cultural appropriateness for the Indonesian context | LLM judge (rubric) |
| register | formality register: baku / santai / jaksel | LLM judge (rubric) |
| codemix | Indonesian-English code-mixing robustness | LLM judge (rubric) |

## The calibration study (M2)

LLM judges are tuned on English; nobody has published agreement numbers for
Bahasa Indonesia. `ideval calibrate` measures judge-vs-ground-truth agreement
(Cohen's kappa, Spearman) across API judges and small local judges, and renders
the results table here.

<!-- calibration:start -->
| judge | subject | suite | n | kappa | precision | recall | spearman | err |
|---|---|---|---:|---:|---:|---:|---:|---:|
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual | 10 | 1.000 | 1.000 | 1.000 | 1.000 | 0 |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.900 | 1.000 | - | 0 |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual | 8 | -0.143 | 0.857 | 0.857 | 0.260 | 2 |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual | 10 | 0.737 | 0.667 | 1.000 | 0.764 | 0 |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual | 10 | 0.737 | 0.667 | 1.000 | 0.861 | 0 |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual | 10 | 0.286 | 0.333 | 1.000 | 0.456 | 0 |
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 1.000 | 1.000 | 1 |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 1.000 | 1.000 | 1 |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual_indommlu | 76 | 0.134 | 0.808 | 0.396 | 0.186 | 4 |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.969 | 0.957 | 1.000 | 0.970 | 0 |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.969 | 0.957 | 1.000 | 0.984 | 0 |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual_indommlu | 74 | 0.202 | 0.435 | 0.455 | 0.194 | 6 |
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.109 | 0.789 | 0.968 | 0.151 | 0 |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.109 | 0.789 | 0.968 | 0.085 | 0 |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual_tydiqa | 37 | -0.029 | 0.773 | 0.586 | 0.010 | 3 |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.385 | 0.808 | 0.778 | 0.483 | 0 |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.525 | 0.828 | 0.889 | 0.582 | 0 |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual_tydiqa | 35 | 0.295 | 0.867 | 0.542 | 0.381 | 5 |
<!-- calibration:end -->

## License

MIT

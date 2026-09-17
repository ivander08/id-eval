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
ideval run factual --model ollama/qwen2.5:1.5b --judge ollama/qwen2.5:1.5b
```

Models follow `provider/model-id` syntax. Providers: `openai` (any OpenAI-compatible
endpoint via `OPENAI_API_KEY`/`OPENAI_BASE_URL`), `openrouter`, `kenari`
(`https://kenari.id/v1`, reads `OPENAI_API_KEY`), `ollama`.

## Suites

| suite | what it measures | ground truth |
|---|---|---|
| factual | Indonesian factual QA (hand-curated seeds) | exact match |
| factual_indommlu | Indonesian multiple-choice, MMLU-style (IndoMMLU) | exact match (choice letter) |
| factual_tydiqa | Indonesian extractive QA with context (TyDiQA) | exact match |
| cultural | cultural appropriateness for the Indonesian context | LLM judge (rubric) |
| register | formality register: baku / santai / jaksel | LLM judge (rubric) |
| codemix | Indonesian-English code-mixing robustness | LLM judge (rubric) |

## The calibration study (M2)

LLM judges are tuned on English; nobody has published agreement numbers for
Bahasa Indonesia. `ideval calibrate` measures judge-vs-ground-truth agreement
(Cohen's kappa, Spearman) across API judges and small local judges, and renders
the results table here.

<!-- calibration:start -->
| judge | subject | suite | n | kappa | pabak | precision | recall | spearman | err | flags |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.800 | 0.900 | 1.000 | - | 0 | low-n, prevalence |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.800 | 0.900 | 1.000 | - | 0 | low-n, prevalence |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual | 9 | 0.270 | 0.333 | 1.000 | 0.625 | 0.395 | 1 | low-n |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual | 10 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | low-n |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual | 10 | 1.000 | 1.000 | 1.000 | 1.000 | 0.943 | 0 | low-n |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual | 9 | 0.571 | 0.556 | 1.000 | 0.667 | 0.612 | 1 | low-n, self-judge |
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1 |  |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1 |  |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual_indommlu | 74 | 0.023 | -0.135 | 0.750 | 0.333 | 0.042 | 6 |  |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.942 | 0.950 | 0.960 | 0.960 | 0.942 | 0 |  |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.971 | 0.975 | 0.962 | 1.000 | 0.972 | 0 |  |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual_indommlu | 72 | 0.043 | 0.167 | 0.333 | 0.364 | 0.111 | 8 | self-judge |
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.217 | 0.550 | 0.784 | 0.967 | 0.274 | 0 |  |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.273 | 0.600 | 0.789 | 1.000 | 0.397 | 0 |  |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual_tydiqa | 37 | -0.021 | 0.135 | 0.750 | 0.643 | 0.013 | 3 |  |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.536 | 0.550 | 0.792 | 0.826 | 0.576 | 0 |  |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.571 | 0.600 | 0.759 | 0.957 | 0.612 | 0 |  |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual_tydiqa | 37 | 0.145 | 0.135 | 0.647 | 0.524 | 0.101 | 3 | self-judge |
<!-- calibration:end -->

The `flags` column marks cells that cannot be read at face value: `low-n`
(`n < 30`, where one flipped case moves kappa by ~0.1), `prevalence`
(`pe >= 0.80`, where kappa collapses regardless of how well the judge agrees),
and `self-judge` (subject == judge, which is confounded by self-preference bias).
`pabak` is `2·po − 1` and carries no prevalence term, so it stays readable where
kappa does not.

[`docs/design-notes.md`](docs/design-notes.md) records why each of these choices
was made, what it costs, the published evidence behind it, and what id-eval still
gets wrong.

## License

MIT

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
| judge | subject | suite | n | kappa | pabak | retest | frame | precision | recall | spearman | err | flags |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.800 | 1.000 | 1.000 | 0.900 | 1.000 | - | 0 | low-n, prevalence |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.800 | 1.000 | 1.000 | 0.900 | 1.000 | 1.000 | 0 | low-n, prevalence |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual | 10 | 0.138 | 0.000 | 0.800 | 0.500 | 1.000 | 0.444 | 0.272 | 0 | low-n, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual | 10 | 0.583 | 0.600 | 0.967 | 0.900 | 0.750 | 0.750 | 0.583 | 0 | low-n |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual | 10 | 0.800 | 0.800 | 1.000 | 1.000 | 0.800 | 1.000 | 0.746 | 0 | low-n |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual | 10 | 0.400 | 0.400 | 0.817 | 0.500 | 0.600 | 0.750 | 0.511 | 0 | low-n, self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 0.962 | 0.886 | 1.000 | 1.000 | 1.000 | 1 |  |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1 |  |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual_indommlu | 79 | 0.015 | -0.013 | 0.765 | 0.474 | 0.667 | 0.462 | 0.089 | 1 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.886 | 0.900 | 0.983 | 0.963 | 0.923 | 0.923 | 0.886 | 0 |  |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.915 | 0.925 | 1.000 | 1.000 | 0.926 | 0.962 | 0.916 | 0 |  |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.281 | 0.375 | 0.758 | 0.450 | 0.520 | 0.500 | 0.271 | 0 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/qwen3-8-flash | factual_tydiqa | 39 | 0.155 | 0.641 | 0.991 | 0.974 | 0.838 | 0.969 | 0.194 | 1 |  |
| kenari/glm-5-3-flash | kenari/qwen3-8-flash | factual_tydiqa | 39 | 0.155 | 0.641 | 0.991 | 0.974 | 0.838 | 0.969 | 0.194 | 1 |  |
| ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | factual_tydiqa | 39 | 0.247 | 0.333 | 0.791 | 0.436 | 0.913 | 0.656 | 0.237 | 1 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.545 | 0.600 | 0.975 | 0.925 | 0.821 | 0.885 | 0.587 | 0 |  |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.581 | 0.650 | 0.975 | 0.925 | 0.806 | 0.962 | 0.639 | 0 |  |
| ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.126 | 0.100 | 0.792 | 0.475 | 0.722 | 0.500 | 0.131 | 0 | self-judge, unstable, framing-sensitive |
<!-- calibration:end -->

The `flags` column marks cells that cannot be read at face value: `low-n`
(`n < 30`, where one flipped case moves kappa by ~0.1), `prevalence`
(`pe >= 0.80`, where kappa collapses regardless of how well the judge agrees),
`self-judge` (subject == judge, which is confounded by self-preference bias),
`unstable` (`test_retest < 0.90`, the judge does not agree with itself run to
run), and `framing-sensitive` (`framing_agreement < 0.80`, moving the rubric
changes the verdict). `pabak` is `2·po − 1` and carries no prevalence term, so it
stays readable where kappa does not.

`retest` and `frame` are the two reliability axes, measured with `--repeats N`:
every case is judged `N` times, alternating the rubric's position relative to the
response. `retest` is the mean share of draws agreeing with their item's majority
label; `frame` is how often the two framings reach the same majority verdict.
Both render `-` on a single-pass run.

[`docs/design-notes.md`](docs/design-notes.md) records why each of these choices
was made, what it costs, the published evidence behind it, and what id-eval still
gets wrong.

## License

MIT

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

| suite | cases | what it measures | ground truth |
|---|---:|---|---|
| factual | 32 | Indonesian factual QA, hand-curated across geography, dates, figures and state | exact match |
| factual_indommlu | 80 | Indonesian multiple-choice, MMLU-style (IndoMMLU) | exact match (choice letter) |
| factual_tydiqa | 40 | Indonesian extractive QA with context (TyDiQA) | exact match |
| cultural | 32 | cultural appropriateness for the Indonesian context | LLM judge (rubric) |
| register | 32 | formality register: baku / santai / jaksel | LLM judge (rubric) |
| codemix | 32 | Indonesian-English code-mixing robustness | LLM judge (rubric) |

Every suite carries at least 32 cases, so no calibration row is flagged `low-n`.

## The calibration study (M2)

LLM judges are tuned on English; nobody has published agreement numbers for
Bahasa Indonesia. `ideval calibrate` measures judge-vs-ground-truth agreement
(Cohen's kappa, Spearman) across API judges and small local judges, and renders
the results table here.

<!-- calibration:start -->
| judge | vs | subject | suite | n | kappa | pabak | retest | frame | precision | recall | spearman | err | flags |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual | 32 | 0.000 | 0.938 | 0.990 | 1.000 | 0.969 | 1.000 | 1.000 | 0 | prevalence |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual | 32 | 0.000 | 0.938 | 1.000 | 1.000 | 0.969 | 1.000 | 1.000 | 0 | prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual | 32 | 0.090 | 0.250 | 0.790 | 0.581 | 1.000 | 0.613 | 0.236 | 0 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual | 32 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 | 0 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual | 32 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 | 0 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual | 32 | 0.584 | 0.625 | 0.802 | 0.562 | 0.727 | 0.727 | 0.539 | 0 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual_indommlu | 72 | 1.000 | 1.000 | 0.981 | 0.944 | 1.000 | 1.000 | 1.000 | 8 |  |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual_indommlu | 72 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 8 |  |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual_indommlu | 72 | 0.118 | 0.056 | 0.807 | 0.571 | 0.759 | 0.449 | 0.157 | 8 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 1.000 | 1.000 | 0.975 | 0.925 | 1.000 | 1.000 | 1.000 | 0 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.968 | 0.975 | 0.996 | 1.000 | 0.955 | 1.000 | 0.983 | 0 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.096 | 0.225 | 0.756 | 0.397 | 0.321 | 0.429 | 0.118 | 0 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | -0.094 | 0.650 | 0.975 | 0.925 | 0.917 | 0.892 | -0.095 | 0 | prevalence |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | -0.039 | 0.800 | 1.000 | 1.000 | 0.923 | 0.973 | -0.046 | 0 | prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | -0.032 | 0.100 | 0.808 | 0.487 | 0.913 | 0.568 | -0.086 | 0 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.452 | 0.500 | 0.967 | 0.925 | 0.778 | 0.840 | 0.455 | 0 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.600 | 0.650 | 0.975 | 0.925 | 0.800 | 0.960 | 0.672 | 0 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.309 | 0.300 | 0.825 | 0.500 | 0.789 | 0.600 | 0.256 | 0 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | kenari/qwen3-8-flash | cultural | 32 | 0.079 | 0.500 | 0.948 | 0.875 | 0.920 | 0.793 | 0.553 | 0 |  |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | cultural | 32 | 0.126 | 0.188 | 0.846 | 0.609 | 0.600 | 0.833 | 0.222 | 0 | unstable, framing-sensitive |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | cultural | 32 | 0.235 | 0.312 | 0.867 | 0.672 | 0.621 | 1.000 | 0.240 | 0 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | cultural | 32 | - | 1.000 | 0.995 | 0.984 | - | - | 0.598 | 0 | prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | cultural | 32 | 0.000 | 0.062 | 0.885 | 0.672 | - | 0.000 | 0.184 | 0 | unstable, framing-sensitive, self-judge |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | cultural | 32 | 0.000 | 0.062 | 0.880 | 0.656 | - | 0.000 | -0.004 | 0 | unstable, framing-sensitive, self-judge |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | kenari/qwen3-8-flash | register | 32 | 0.739 | 0.812 | 0.953 | 0.953 | 0.920 | 0.958 | 0.745 | 0 |  |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | register | 32 | -0.019 | 0.375 | 0.938 | 0.875 | 0.840 | 0.778 | -0.163 | 0 |  |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | register | 32 | -0.048 | 0.312 | 0.953 | 0.891 | 0.833 | 0.741 | -0.138 | 0 |  |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | register | 32 | - | 1.000 | 0.995 | 1.000 | - | - | 0.685 | 0 | prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | register | 32 | 0.000 | -0.125 | 0.909 | 0.742 | - | 0.000 | -0.011 | 0 | framing-sensitive, self-judge |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | register | 32 | 0.000 | -0.125 | 0.903 | 0.742 | - | 0.000 | -0.254 | 0 | framing-sensitive, self-judge |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | kenari/qwen3-8-flash | codemix | 32 | 0.652 | 0.938 | 1.000 | 1.000 | 0.968 | 1.000 | 0.590 | 0 | prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | codemix | 32 | -0.049 | 0.750 | 0.979 | 0.938 | 0.903 | 0.966 | 0.143 | 0 | prevalence |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | codemix | 32 | -0.081 | 0.688 | 0.979 | 0.938 | 0.900 | 0.931 | -0.191 | 0 | prevalence |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | codemix | 32 | 0.652 | 0.938 | 0.990 | 0.969 | 1.000 | 0.500 | 0.711 | 0 | prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | codemix | 32 | 0.007 | -0.750 | 0.971 | 0.922 | 1.000 | 0.034 | -0.008 | 0 | self-judge |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | codemix | 32 | 0.014 | -0.688 | 0.971 | 0.922 | 1.000 | 0.069 | -0.169 | 0 | self-judge |
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

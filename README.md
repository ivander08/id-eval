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
| judge | vs | subject | suite | n | kappa | pabak | retest | frame | precision | recall | spearman | err | flags |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.800 | 0.967 | 0.900 | 0.900 | 1.000 | - | 0 | low-n, prevalence |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual | 10 | 0.000 | 0.800 | 1.000 | 1.000 | 0.900 | 1.000 | 1.000 | 0 | low-n, prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual | 10 | -0.176 | 0.200 | 0.750 | 0.400 | 0.857 | 0.667 | 0.199 | 0 | low-n, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual | 10 | 0.783 | 0.800 | 1.000 | 1.000 | 1.000 | 0.750 | 0.802 | 0 | low-n |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual | 10 | 0.783 | 0.800 | 1.000 | 1.000 | 1.000 | 0.750 | 0.802 | 0 | low-n |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual | 10 | 0.348 | 0.400 | 0.867 | 0.700 | 0.667 | 0.500 | 0.529 | 0 | low-n, self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 0.979 | 0.937 | 1.000 | 1.000 | 1.000 | 1 |  |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual_indommlu | 79 | 1.000 | 1.000 | 0.996 | 0.987 | 1.000 | 1.000 | 1.000 | 1 |  |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual_indommlu | 79 | 0.097 | 0.038 | 0.771 | 0.500 | 0.794 | 0.466 | 0.126 | 1 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 1.000 | 1.000 | 0.979 | 0.938 | 1.000 | 1.000 | 1.000 | 0 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.070 | 0.225 | 0.762 | 0.400 | 0.308 | 0.381 | 0.095 | 0 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.231 | 0.600 | 0.983 | 0.950 | 0.833 | 0.938 | 0.250 | 0 |  |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.082 | 0.550 | 0.992 | 0.975 | 0.811 | 0.938 | 0.095 | 0 |  |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.021 | 0.050 | 0.774 | 0.410 | 0.810 | 0.531 | 0.124 | 0 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | kenari/qwen3-8-flash | cultural | 18 | 0.640 | 0.889 | 0.991 | 0.972 | 0.941 | 1.000 | 0.730 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | cultural | 18 | 0.137 | 0.222 | 0.875 | 0.639 | 0.588 | 1.000 | 0.377 | 0 | low-n, unstable, framing-sensitive |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | cultural | 18 | 0.270 | 0.333 | 0.866 | 0.611 | 0.625 | 1.000 | 0.408 | 0 | low-n, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | cultural | 18 | 1.000 | 1.000 | 0.991 | 0.972 | 1.000 | 1.000 | 0.614 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | cultural | 18 | 0.111 | 0.111 | 0.861 | 0.611 | 1.000 | 0.111 | -0.019 | 0 | low-n, unstable, framing-sensitive, self-judge |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | cultural | 18 | 0.111 | 0.111 | 0.870 | 0.639 | 1.000 | 0.111 | -0.069 | 0 | low-n, unstable, framing-sensitive, self-judge |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | kenari/qwen3-8-flash | register | 18 | 0.640 | 0.889 | 0.991 | 1.000 | 0.941 | 1.000 | 0.662 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | register | 18 | -0.059 | 0.778 | 0.926 | 0.833 | 0.941 | 0.941 | 0.028 | 0 | low-n, prevalence |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | register | 18 | -0.080 | 0.667 | 0.935 | 0.833 | 0.938 | 0.882 | 0.013 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | register | 18 | - | 1.000 | 0.991 | 1.000 | - | - | 0.584 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | register | 18 | -0.000 | -0.333 | 0.903 | 0.750 | - | 0.000 | 0.084 | 0 | low-n, framing-sensitive, self-judge |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | register | 18 | -0.000 | -0.333 | 0.912 | 0.750 | - | 0.000 | -0.271 | 0 | low-n, framing-sensitive, self-judge |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | kenari/qwen3-8-flash | codemix | 18 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.339 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | codemix | 18 | -0.059 | 0.778 | 0.986 | 0.972 | 0.941 | 0.941 | 0.475 | 0 | low-n, prevalence |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | kenari/qwen3-8-flash | codemix | 18 | -0.059 | 0.778 | 0.986 | 0.972 | 0.941 | 0.941 | 0.559 | 0 | low-n, prevalence |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.578 | 0.600 | 0.958 | 0.950 | 0.913 | 0.778 | 0.638 | 0 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.826 | 0.850 | 0.983 | 0.950 | 0.929 | 0.963 | 0.747 | 0 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.240 | 0.200 | 0.778 | 0.410 | 0.824 | 0.519 | 0.288 | 0 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | codemix | 18 | 1.000 | 1.000 | 0.991 | 0.972 | 1.000 | 1.000 | 0.422 | 0 | low-n |
| kenari/deepseek-v4-1-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | codemix | 18 | 0.049 | -0.444 | 0.963 | 0.889 | 1.000 | 0.188 | -0.136 | 0 | low-n, self-judge |
| kenari/glm-5-3-flash | ollama/qwen2.5:1.5b | ollama/qwen2.5:1.5b | codemix | 18 | 0.049 | -0.444 | 0.972 | 0.917 | 1.000 | 0.188 | -0.359 | 0 | low-n, self-judge |
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

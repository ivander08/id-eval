# id-eval

Indonesian LLM evaluation toolkit: curated suites, calibrated LLM-as-judge, CI-ready.

## Status

Work in progress. Milestones:

- [x] M0 — scaffold, CLI, schema, suites seeds, tests
- [ ] M1 — deepeval metric classes + runner hardening + ~200 curated cases
- [ ] M2 — `ideval calibrate`: judge agreement study (Cohen's kappa, Spearman)
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

## License

MIT

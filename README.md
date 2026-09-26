# id-eval

Indonesian LLM evaluation toolkit: curated suites, calibrated LLM-as-judge, CI-ready.

## Status

M0–M3 are complete. M4 is built and verified locally; the PyPI upload is a manual step.

- [x] M0 — scaffold, CLI, schema, suites seeds, tests
- [x] M1 — deepeval metric classes + runner hardening + ~200 curated cases
- [x] M2 — `ideval calibrate`: judge agreement study (Cohen's kappa, Spearman)
- [x] M3 — CI eval job, published calibration table, [write-up](https://github.com/ivander08/id-eval/blob/main/docs/blog-indonesian-judge-calibration.md)
- [ ] M4 — PyPI release: the wheel builds, installs from a clean venv and is verified against HEAD

## Install

```bash
pip install -e ".[dev]"   # dev install
```

## Usage

```bash
ideval list-suites
ideval run factual --model ollama/qwen2.5:1.5b --judge ollama/qwen2.5:1.5b
ideval calibrate --suite factual --subject ollama/qwen2.5:1.5b --judge ollama/qwen2.5:1.5b
python scripts/check_suites.py          # offline suite gate, no network or API key
python scripts/check_labels.py          # offline rubric-label gate
python scripts/check_dist.py            # pre-upload: newest dist/ wheel vs this tree
```

`--judge-backend deepeval` runs judging through deepeval's `GEval` instead of the
native JSON-contract prompt, reusing the same provider routing and score scale.
It is opt-in: the published calibration table below was produced by the native
path. See [`docs/design-notes.md`](https://github.com/ivander08/id-eval/blob/main/docs/design-notes.md#9-the-geval-backend-is-opt-in-and-what-that-cost) §9. It needs the optional
extra: `pip install "id-eval[deepeval]"`.

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
| judge | vs | subject | suite | n | kappa | pabak | retest | frame | precision | recall | spearman | err | subj_err | canary | draws | k03 | k07 | flags |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual | 32 | 0.000 | 0.938 | 0.990 | 1.000 | 0.969 | 1.000 | 1.000 | 0 | 0 | - | 0/96 | 0.000 | 1.000 | prevalence |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual | 32 | 0.000 | 0.938 | 1.000 | 1.000 | 0.969 | 1.000 | 1.000 | 0 | 0 | - | 0/96 | 0.000 | 1.000 | prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual | 32 | 0.090 | 0.250 | 0.790 | 0.581 | 1.000 | 0.613 | 0.236 | 0 | 0 | - | 6/96 | 0.102 | 0.090 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual | 32 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 | 0 | 0 | - | 0/96 | 1.000 | 0.929 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual | 32 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.993 | 0 | 0 | - | 0/96 | 1.000 | 1.000 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual | 32 | 0.584 | 0.625 | 0.802 | 0.562 | 0.727 | 0.727 | 0.539 | 0 | 0 | - | 6/96 | 0.525 | 0.584 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual_indommlu | 72 | 1.000 | 1.000 | 0.981 | 0.944 | 1.000 | 1.000 | 1.000 | 0 | 8 | - | 0/216 | 1.000 | 1.000 |  |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual_indommlu | 72 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0 | 8 | - | 0/216 | 1.000 | 1.000 |  |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual_indommlu | 72 | 0.118 | 0.056 | 0.807 | 0.571 | 0.759 | 0.449 | 0.157 | 0 | 8 | - | 23/216 | 0.118 | 0.167 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 1.000 | 1.000 | 0.975 | 0.925 | 1.000 | 1.000 | 1.000 | 0 | 0 | - | 0/240 | 1.000 | 1.000 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.968 | 0.975 | 0.996 | 1.000 | 0.955 | 1.000 | 0.983 | 0 | 0 | - | 0/240 | 0.968 | 1.000 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual_indommlu | 80 | 0.096 | 0.225 | 0.756 | 0.397 | 0.321 | 0.429 | 0.118 | 0 | 0 | - | 23/240 | 0.096 | 0.123 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | -0.071 | 0.700 | 0.975 | 0.925 | 0.944 | 0.895 | -0.076 | 0 | 0 | - | 0/120 | -0.071 | -0.071 | prevalence |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | -0.034 | 0.850 | 1.000 | 1.000 | 0.949 | 0.974 | -0.037 | 0 | 0 | - | 0/120 | -0.034 | -0.034 | prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | factual_tydiqa | 40 | 0.017 | 0.150 | 0.808 | 0.487 | 0.957 | 0.579 | 0.011 | 0 | 0 | - | 7/120 | 0.017 | 0.005 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.452 | 0.500 | 0.967 | 0.925 | 0.778 | 0.840 | 0.455 | 0 | 0 | - | 0/120 | 0.452 | 0.452 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.600 | 0.650 | 0.975 | 0.925 | 0.800 | 0.960 | 0.672 | 0 | 0 | - | 0/120 | 0.652 | 0.680 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | factual_tydiqa | 40 | 0.309 | 0.300 | 0.825 | 0.500 | 0.789 | 0.600 | 0.256 | 0 | 0 | - | 6/120 | 0.309 | 0.229 | self-judge, unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | cultural | 32 | 0.207 | 0.625 | 0.927 | 0.812 | 1.000 | 0.806 | 0.580 | 0 | 0 | 0/1 | 0/96 | 0.368 | 0.535 |  |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | cultural | 32 | 0.475 | 0.875 | 0.969 | 0.938 | 1.000 | 0.935 | 0.390 | 0 | 0 | 0/1 | 0/96 | 1.000 | 0.304 | prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | cultural | 32 | 0.080 | 0.188 | 0.766 | 0.406 | 1.000 | 0.581 | 0.253 | 0 | 0 | 0/1 | 8/96 | 0.207 | 0.038 | unstable, framing-sensitive |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | cultural | 32 | 0.000 | 0.812 | 1.000 | 1.000 | - | 0.000 | 0.424 | 0 | 0 | 0/1 | 0/96 | 0.264 | - | prevalence |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | cultural | 32 | 0.000 | 0.812 | 0.990 | 0.969 | - | 0.000 | 0.371 | 0 | 0 | 0/1 | 0/96 | 0.351 | - | prevalence |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | cultural | 32 | -0.053 | 0.000 | 0.771 | 0.344 | 0.067 | 0.333 | -0.083 | 0 | 0 | 1/1 | 3/96 | 0.003 | 0.000 | self-judge, unstable, framing-sensitive, canary-fail, threshold-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | register | 32 | 0.207 | 0.625 | 0.938 | 0.938 | 1.000 | 0.806 | 0.387 | 0 | 0 | 0/1 | 0/96 | 0.297 | 0.162 |  |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | register | 32 | 0.176 | 0.562 | 0.969 | 0.969 | 1.000 | 0.774 | 0.338 | 0 | 0 | 0/1 | 0/96 | 0.245 | 0.096 |  |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | register | 32 | 0.297 | 0.750 | 0.938 | 0.812 | 1.000 | 0.871 | 0.134 | 0 | 0 | 0/1 | 8/96 | 0.000 | 0.191 | prevalence |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | register | 32 | 0.000 | -0.062 | 1.000 | 1.000 | - | 0.000 | 0.292 | 0 | 0 | 0/1 | 0/96 | 0.111 | 0.000 |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | register | 32 | 0.000 | -0.062 | 0.990 | 1.000 | - | 0.000 | 0.361 | 0 | 0 | 0/1 | 0/96 | 0.111 | 0.000 |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | register | 32 | 0.055 | 0.062 | 0.817 | 0.484 | 0.556 | 0.588 | 0.193 | 0 | 0 | 0/1 | 8/96 | -0.045 | 0.071 | self-judge, unstable, framing-sensitive, threshold-sensitive |
| kenari/deepseek-v4-1-flash | truth | kenari/qwen3-8-flash | codemix | 32 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.270 | 0 | 0 | 0/1 | 0/96 | 1.000 | 0.467 | prevalence |
| kenari/glm-5-3-flash | truth | kenari/qwen3-8-flash | codemix | 32 | 0.652 | 0.938 | 1.000 | 1.000 | 1.000 | 0.968 | 0.452 | 0 | 0 | 0/1 | 0/96 | 1.000 | 0.784 | prevalence |
| ollama/qwen2.5:1.5b | truth | kenari/qwen3-8-flash | codemix | 32 | -0.049 | 0.750 | 0.958 | 0.875 | 0.966 | 0.903 | -0.169 | 0 | 0 | 1/1 | 3/96 | -0.032 | -0.118 | prevalence, canary-fail |
| kenari/deepseek-v4-1-flash | truth | ollama/qwen2.5:1.5b | codemix | 32 | 0.033 | -0.250 | 0.990 | 0.969 | 1.000 | 0.048 | 0.452 | 0 | 0 | 0/1 | 0/96 | 0.103 | - |  |
| kenari/glm-5-3-flash | truth | ollama/qwen2.5:1.5b | codemix | 32 | 0.067 | -0.188 | 0.990 | 0.969 | 1.000 | 0.095 | 0.451 | 0 | 0 | 0/1 | 0/96 | 0.189 | - |  |
| ollama/qwen2.5:1.5b | truth | ollama/qwen2.5:1.5b | codemix | 32 | -0.005 | 0.250 | 0.953 | 0.875 | 0.655 | 0.905 | 0.004 | 0 | 0 | 1/1 | 7/96 | 0.116 | 0.000 | self-judge, canary-fail, threshold-sensitive |
<!-- calibration:end -->

The `flags` column marks cells that cannot be read at face value: `low-n`
(`n < 30`, where one flipped case moves kappa by ~0.1), `prevalence`
(`pe >= 0.80`, where kappa collapses regardless of how well the judge agrees),
`self-judge` (subject == judge, which is confounded by self-preference bias),
`unstable` (`test_retest < 0.90`, the judge does not agree with itself run to
run), `framing-sensitive` (`framing_agreement < 0.80`, moving the rubric changes
the verdict), `canary-fail` (the judge passed an adversarial case that was written
to be scored `0.0`), and `threshold-sensitive` (the kappa sweep at `0.3`/`0.5`/`0.7`
changes sign, so the row's claim depends on where the pass/fail line is drawn).
`pabak` is `2·po − 1` and carries no prevalence term, so it stays readable where
kappa does not.

`retest` and `frame` are the two reliability axes, measured with `--repeats N`:
every case is judged `N` times, alternating the rubric's position relative to the
response. `retest` is the mean share of draws agreeing with their item's majority
label; `frame` is how often the two framings reach the same majority verdict.
Both render `-` on a single-pass run.

`canary` is the adversarial-case column: `passed/attempted` for the cases whose
`reference_note` starts with `ADVERSARIAL`, where a *pass* is the failure the case
exists to catch. A case counts as passed if the judge scored it at or above `0.5` on
**any** draw, not just the headline first draw — the judge's headline verdict is the
first successful draw, so reading it alone would hide an intermittent pass. The
three canaries are `cult-018`, `reg-018` and `cmx-018`; the
factual suites carry none, so their cells render `-`. `draws` is
`unparsed/attempted` verdicts — per-draw, not per-case, which is why a row can show
`err = 0` (no case failed on *every* draw) beside a non-zero `draws`. `subj_err` is
the other half of coverage: cases the subject model failed, which the judge never
saw. `n + err + subj_err` is the suite's case count for every row. `k03`/`k07`
repeat the row's kappa at `0.3` and `0.7` so a reader can see whether the sign is an
artifact of the `0.5` convention; `-` means kappa is undefined there (`pe = 1.0`).

**The rubric rows are judge-vs-truth against reviewed, machine-authored labels.** `cultural`,
`register` and `codemix` have no `expected` value, so round 1 could only calibrate
them by comparing judges with each other. `annotations/rubric_labels.jsonl` now
supplies a `0.0`/`0.5`/`1.0` label per (suite, case, subject) — 96 cases x 2
subjects — and those rows read `vs = truth` against it. Every one of the 192 rows
has been through a second pass (`rater: review:assistant`) that re-read each
response against its suite's rubric via `scripts/label_review.py`, and that pass
changed 4 labels. It was not a human pass, so the labels remain the single point of
failure for the rubric rows: they replace "two judges agree" with "one judge agrees
with one rater", and a second model reading the same drafts shares the first pass's
blind spots in a way an independent human would not. [`docs/design-notes.md`](https://github.com/ivander08/id-eval/blob/main/docs/design-notes.md#11-closing-the-gaps-8-recorded-and-what-stays-open)
§11 states the limitation and reports the resulting kappa.

**The table was regenerated offline**, from the stored `results_calibration.json`
via `scripts/replay_calibration.py`, not by a new `calibrate` run: `adapters.chat`
pins no temperature, so a fresh run would judge different text and every number
would move for reasons unrelated to this change. The judge verdicts in the table
are the M2 study's; only the ground-truth column for the 18 rubric rows is new.

[`docs/calibration-study.md`](https://github.com/ivander08/id-eval/blob/main/docs/calibration-study.md) is the write-up: the
design, the kappa-collapse rows, the reliability gap between the API judges and
the local one, and what the study still gets wrong.
[`docs/design-notes.md`](https://github.com/ivander08/id-eval/blob/main/docs/design-notes.md) records why each of these choices
was made, what it costs, the published evidence behind it, and what id-eval still
gets wrong.

## CI

`.github/workflows/eval.yml` runs two jobs. `suites` runs offline on every push
and pull request — it loads all six suites and fails on a dropped case, a
duplicated input, a broken judge canary, or a suite that has shrunk below the
`low-n` threshold. It also validates `annotations/rubric_labels.jsonl` — row key
shape, the `0.0`/`0.5`/`1.0` scale, rectangular coverage, and that the three
canaries stay `0.0`. It also builds a wheel and checks it against the tree
(`scripts/check_dist.py`), so a `[tool.hatch.build]` change that drops a module or
a suite fails in CI rather than at upload. `calibrate` runs weekly and on dispatch
only (it needs `OPENAI_API_KEY` and mutates a tracked file), and is a smoke run, not
the study above.

## License

MIT

# Calibrating an LLM judge on Bahasa Indonesia

## Why this exists

LLM-as-a-judge is the default scoring path for open-ended generation, and the
judges are tuned on English. No published agreement number exists for Bahasa
Indonesia. This is the measurement behind the table in the README, written out so
the numbers can be read as a study rather than as a leaderboard.

## The design

`ideval calibrate` runs two protocols over the same subject outputs, because only
three of the six suites have something to compare a judge against.

| suite | cases | ground truth | protocol |
|---|---:|---|---|
| `factual` | 32 | exact match | judge vs ground truth |
| `factual_indommlu` | 80 | exact match (choice letter) | judge vs ground truth |
| `factual_tydiqa` | 40 | exact match | judge vs ground truth |
| `cultural` | 32 | none | inter-judge agreement |
| `register` | 32 | none | inter-judge agreement |
| `codemix` | 32 | none | inter-judge agreement |

For the three scoreable suites a judge is scored against the matcher's verdict,
and the report carries Cohen's kappa, observed agreement `po`, PABAK, precision,
recall and Spearman. For the three rubric suites there is no numeric ground
truth, so every unordered judge pair is compared instead — one row per pair,
labelled `vs <judge>` in the table.

Subjects: `kenari/qwen3-8-flash` and `ollama/qwen2.5:1.5b`. Judges:
`kenari/deepseek-v4-1-flash`, `kenari/glm-5-3-flash` and `ollama/qwen2.5:1.5b`.
248 cases, `--repeats 3`, 36 rows, 1464 pair rows.

`--repeats 3` judges every case three times and alternates the rubric's position
relative to the response, which yields the two reliability columns. `retest` is
the mean share of draws agreeing with their item's majority label; `frame` is how
often the two framings reach the same majority verdict. Both are undefined on a
single-pass run and render `-`.

## The headline: kappa collapses on this ground truth

Two rows from the shipped artifact, both real output:

| judge | subject | suite | n | po | kappa | pabak |
|---|---|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | `kenari/qwen3-8-flash` | factual | 32 | 0.969 | **0.000** | 0.938 |
| `kenari/glm-5-3-flash` | `kenari/qwen3-8-flash` | factual_tydiqa | 40 | 0.900 | **−0.039** | 0.800 |

The first judge agreed with ground truth **31 times out of 32** and is reported as
`kappa = 0.000`. The second agreed **36 times out of 40** and is reported as a
*negative* kappa. Read only the kappa column and both judges look worthless, or
worse than worthless.

The mechanism is prevalence. On `factual / kenari/qwen3-8-flash` the ground truth
pass rate is `0.938`, so chance agreement `pe` is `0.938` too; with `po = 0.969`
kappa is `(0.969 − 0.938) / (1 − 0.938) ≈ 0.000`. Correcting the matcher raised
the pass rate further and pushed kappa *down* while `po` went *up* — the paradox
getting worse because the instrument got better.

`pabak = 2·po − 1` carries no prevalence term. It reads `0.938` and `0.800` on
those two rows, which is what the raw agreement actually says. The honest reading
is that kappa is the wrong instrument for a skewed ground truth, not that these
judges are bad. `prevalence` fires on **10 of 36 rows** for exactly this reason.

## The local judge is the unreliable one, and stability says so

The API judges never failed to produce a parseable verdict. The local judge
failed on **7.4%** of individual draws — 108 of 1464 — while every `err` column in
the table reads `0` for it, because a case counts as an error only when *every*
draw failed. Per-draw failure is visible only because `--repeats 3` counts draws.

| judge | rows | retest | frame | draws failed |
|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | 18 | 0.961 | 0.903 | 0 / 1464 |
| `kenari/glm-5-3-flash` | 12 | 0.960 | 0.895 | 0 / 1464 |
| `ollama/qwen2.5:1.5b` | 6 | 0.798 | 0.517 | 108 / 1464 (7.4%) |

The gap is wider on the judge-vs-truth rows alone: `retest` is `0.981` and `0.995`
for the two API judges against `0.798` for the local one, and `frame` is `0.953`
and `0.988` against `0.517`. Every `unstable` row (10 of 36) and every
`framing-sensitive` row (12 of 36) involves the local judge. A judge that cannot
reproduce its own verdict across framings cannot anchor a published number,
regardless of how plausible its reasons read.

This is the second axis of Norman et al.'s protocol, and the one a single-pass
study cannot see. The first table published here had one pass per case and no
`retest` or `frame` column at all.

## Self-judging is confounded, and now measured

9 of 36 rows are `self-judge` — the subject appears on one side of the comparison.
5 of those 9 are additionally both `unstable` and `framing-sensitive`, and all 5
are the local judge grading itself:

| judge | vs | suite | subject | flags |
|---|---|---|---|---|
| `ollama/qwen2.5:1.5b` | truth | factual | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive |
| `ollama/qwen2.5:1.5b` | truth | factual_indommlu | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive |
| `ollama/qwen2.5:1.5b` | truth | factual_tydiqa | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive |
| `kenari/deepseek-v4-1-flash` | `ollama/qwen2.5:1.5b` | cultural | `ollama/qwen2.5:1.5b` | unstable, framing-sensitive, self-judge |
| `kenari/glm-5-3-flash` | `ollama/qwen2.5:1.5b` | cultural | `ollama/qwen2.5:1.5b` | unstable, framing-sensitive, self-judge |

The flag fires when the subject is *either* side of a pair, because self-preference
bias confounds the row regardless of which side the subject sits on. On
`factual / ollama` the local judge grading itself reaches `kappa = 0.584` — the
only self-judge row that looks healthy, and the one least safe to read, since the
subject and the judge share both weights and failure modes.

## What we still get wrong

- **`prevalence` fires on 10 of 36 rows.** Growing the suites fixed `low-n`; it
  cannot fix a skewed ground truth. `design-notes.md` §8.5 has the detail.
- **The three rubric suites have no ground truth at all** — 96 cases scored only
  by comparing judges with each other. Two judges agreeing says nothing about
  whether either is correct. Across the 18 rubric pair rows the two API judges
  agree at a mean `kappa = 0.531` over the four rows where kappa is defined,
  while any pair containing the local judge sits at `0.015`. See §8.1.
- **`low-n` is no longer the binding constraint.** All four hand-authored suites
  were grown to 32 cases, so every row carries `n >= 32` and no row is flagged for
  sample size. What remains is difficulty, which is a property of the
  subject–item pair, not of the item.
- **Pairwise position bias is unmeasured.** Only the pointwise analogue — rubric
  before vs after the response — is covered, by the `frame` column. See §8.2.

## Reproduce it

```bash
export OPENAI_API_KEY=...        # the kenari provider reuses this variable
ideval calibrate \
  --suite factual --suite factual_indommlu --suite factual_tydiqa \
  --suite cultural --suite register --suite codemix \
  --subject kenari/qwen3-8-flash --subject ollama/qwen2.5:1.5b \
  --judge kenari/deepseek-v4-1-flash --judge kenari/glm-5-3-flash \
  --judge ollama/qwen2.5:1.5b \
  --repeats 3 --out results_calibration.json --update-readme
```

`--repeats 3` across all six suites takes roughly six hours, which is why the
table is regenerated by hand and never in CI. The scheduled CI job runs a smoke
calibration (`--repeats 1`, two suites) to prove the pipeline still works; it does
not touch the published numbers.

`results_calibration.json` matches `results*.json` in `.gitignore`, so it is not
committed. The README table is the artifact of record; the pair rows inside the
JSON are what the disagreement analyses in `design-notes.md` §6 are computed from.

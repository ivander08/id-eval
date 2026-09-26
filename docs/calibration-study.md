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
| `cultural` | 32 | rubric labels | judge vs ground truth |
| `register` | 32 | rubric labels | judge vs ground truth |
| `codemix` | 32 | rubric labels | judge vs ground truth |

For the three scoreable suites a judge is scored against the matcher's verdict,
and the report carries Cohen's kappa, observed agreement `po`, PABAK, precision,
recall and Spearman. The three rubric suites have no `expected` value, so they were
originally compared against each other — one row per unordered judge pair,
labelled `vs <judge>`. `annotations/rubric_labels.jsonl` now supplies a
`0.0`/`0.5`/`1.0` label per (suite, case, subject) and those rows read
`vs = truth` against it instead. **The labels went through a drafting pass and a
review pass, both by models**, so the rubric rows now answer "does a judge agree
with one rater" rather than "do two judges agree with each other" — see "What we
still get wrong" below, where the limitation is stated in full.

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
| `kenari/glm-5-3-flash` | `kenari/qwen3-8-flash` | factual_tydiqa | 40 | 0.925 | **−0.034** | 0.850 |

The first judge agreed with ground truth **31 times out of 32** and is reported as
`kappa = 0.000`. The second agreed **37 times out of 40** and is reported as a
*negative* kappa. Read only the kappa column and both judges look worthless, or
worse than worthless.

The mechanism is prevalence. On `factual / kenari/qwen3-8-flash` the ground truth
pass rate is `0.938`, so chance agreement `pe` is `0.938` too; with `po = 0.969`
kappa is `(0.969 − 0.938) / (1 − 0.938) ≈ 0.000`. Correcting the matcher raised
the pass rate further and pushed kappa *down* while `po` went *up* — the paradox
getting worse because the instrument got better.

`pabak = 2·po − 1` carries no prevalence term. It reads `0.938` and `0.850` on
those two rows, which is what the raw agreement actually says. The honest reading
is that kappa is the wrong instrument for a skewed ground truth, not that these
judges are bad. `prevalence` fires on **11 of 36 rows** for exactly this reason.

## The local judge is the unreliable one, and stability says so

The API judges never failed to produce a parseable verdict. The local judge
failed on **7.4%** of individual draws — 108 of 1464 — while every `err` column in
the table reads `0` for it, because a case counts as an error only when *every*
draw failed. Per-draw failure is visible only because `--repeats 3` counts draws.

| judge | rows | retest | frame | draws failed |
|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | 12 | 0.979 | 0.953 | 0 / 1464 |
| `kenari/glm-5-3-flash` | 12 | 0.990 | 0.981 | 0 / 1464 |
| `ollama/qwen2.5:1.5b` | 12 | 0.833 | 0.575 | 108 / 1464 (7.4%) |

The gap is wider on the judge-vs-truth rows alone: `retest` is `0.981` and `0.995`
for the two API judges against `0.798` for the local one, and `frame` is `0.953`
and `0.988` against `0.516`. Every `unstable` row (9 of 36) and every
`framing-sensitive` row (9 of 36) involves the local judge. A judge that cannot
reproduce its own verdict across framings cannot anchor a published number,
regardless of how plausible its reasons read.

This is the second axis of Norman et al.'s protocol, and the one a single-pass
study cannot see. The first table published here had one pass per case and no
`retest` or `frame` column at all.

## Self-judging is confounded, and now measured

6 of 36 rows are `self-judge` — the subject appears on one side of the comparison.
5 of those 6 are additionally both `unstable` and `framing-sensitive`, and all 5
are the local judge grading itself:

| judge | vs | suite | subject | flags |
|---|---|---|---|---|
| `ollama/qwen2.5:1.5b` | truth | factual | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive |
| `ollama/qwen2.5:1.5b` | truth | factual_indommlu | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive |
| `ollama/qwen2.5:1.5b` | truth | factual_tydiqa | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive |
| `ollama/qwen2.5:1.5b` | truth | cultural | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive, threshold-sensitive |
| `ollama/qwen2.5:1.5b` | truth | register | `ollama/qwen2.5:1.5b` | self-judge, unstable, framing-sensitive, threshold-sensitive |

The flag fires when the subject is *either* side of a pair, because self-preference
bias confounds the row regardless of which side the subject sits on. On
`factual / ollama` the local judge grading itself reaches `kappa = 0.584` — the
only self-judge row that looks healthy, and the one least safe to read, since the
subject and the judge share both weights and failure modes. The count fell from 9
to 6, and the change is a consequence of §11.1: six of the old `self-judge` rows
were rubric *pair* rows where the local subject sat on the reference side, so the
flag fired for the two API judges grading it. Those pairs are gone — the rubric
rows are judge-vs-truth now — and three new `self-judge` rows appear in their place,
the local judge grading its own outputs on the three rubric suites. So the flag now
names exactly one confounded judge on six rows instead of spanning two judges on
rows that were never really about self-preference.

## What we still get wrong

- **`prevalence` fires on 11 of 36 rows.** Growing the suites fixed `low-n`; it
  cannot fix a skewed ground truth. `design-notes.md` §8.5 has the detail.
- **The rubric labels are reviewed, but by a second model, not a human.** The three
  rubric suites now carry ground truth — 192 labels, one per (suite, case, subject),
  in `annotations/rubric_labels.jsonl` — so their 18 rows are judge-vs-truth instead
  of inter-judge. Every row's `rater` field reads `review:assistant`: the drafting
  pass (`draft:assistant`) was followed by a second pass that re-read each response
  against its suite's rubric through `scripts/label_review.py` and changed 4 labels
  (`cult-006`, `cult-007`, `cmx-007`, `cmx-008`). That is a real second reading and
  it caught both an over-credited and an under-credited row, but it is another model
  reading the same drafts, so it shares the first pass's blind spots in a way an
  independent human rater would not. The labels are still the single point of
  failure for those rows, and `review:<name>` for a human remains the open hook.
  The mean kappa is `0.235` across the 12 API-judge rubric rows and `0.054` across
  the 6 local-judge ones — lower than the `0.531` the two API judges posted against
  each other, which is the expected direction, since two judges from the same family
  overstate agreement with a third party. `codemix` labels pass `0.812` of the time,
  so its two API rows carry `prevalence` and their kappa is the least readable number
  in the block. See §11.1.
- **`low-n` is no longer the binding constraint.** All four hand-authored suites
  were grown to 32 cases, so every row carries `n >= 32` and no row is flagged for
  sample size. What remains is difficulty, which is a property of the
  subject–item pair, not of the item.
- **Pairwise position bias is measured on one suite, and it is judge-specific.**
  `_judge_pair` presents two responses and swaps which is `A`; the flip rate is the
  share of pairs whose winner changed. On 21 `factual` pairs, both API judges scored
  **`0.000`** — never changed their answer when the responses were swapped, and
  picked the known-better response on every pair. The local judge scored `0.571`
  over the 7 pairs it could answer at all, with 14 pairs producing no majority and
  7 draws failing to parse. This is a separate protocol from the 36-row table — it
  needs two responses per item, so it cannot be a column of it. A `0.0` flip rate
  is a valid result, not an untested one. See §11.2.
- **The exact-match matcher still cannot see paraphrase.** The four measured
  normalizer gaps are fixed, including intra-word joiners (`Al-Qur'an` no longer
  splits into `al qur an`, which was misread as a paraphrase failure on
  `tydiqa-019`). An affix-aware token matcher was written for the remaining
  paraphrase gap and **reverted**: it moved 6 rows to `1.0` that are wrong answers,
  because bag-of-words containment discards word order and the affix strip is not a
  stemmer (`merah → rah`). On the worst cell, 2 of the 6 remaining disagreements are
  the matcher rejecting a correct answer. Closing that needs a semantic matcher or
  a different ground truth, not a wider regex. See §11.3–§11.4.
- **The published table is a replay, not a new run.** `README.md`'s table was
  rebuilt offline from `results_calibration.json` via `scripts/replay_calibration.py`
  so that changing what the rubric rows *mean* would not also change what they
  measure. The judge verdicts are the M2 study's; only the ground truth for the 18
  rubric rows is new.

## Pairwise position bias

The `frame` column measures the pointwise analogue — moving the rubric around a
single response. Position bias proper needs two responses and a swapped
presentation order. `scripts/pairwise_probe.py` runs that protocol on pairs built
from the stored artifact: for a `factual` case, the API judge passed one subject's
output and failed the other's, so the pair has a known better response. Each draw's
verdict is resolved from its letter back to the *response* it named, so the two
orders are compared on content, not on the letter.

`--suite factual --repeats 2`, 21 pairs, from `results_pairwise.json`:

| judge | pairs judged in both orders | flip rate | picked the known-better response | unparsed draws |
|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | 20 | **0.000** | 1.000 | 0 |
| `kenari/glm-5-3-flash` | 21 | **0.000** | 1.000 | 0 |
| `ollama/qwen2.5:1.5b` | 7 | **0.571** | 0.571 | 7 |

Both API judges picked the known-better response on every pair and never changed
their answer when the responses were swapped. That is a `0.0` flip rate, and it is
a result rather than an absence of one: the pairwise form of position bias does not
fire on these judges, this suite and this pair construction. The one `deepseek`
pair excluded (`fact-007`) had two forward draws split `A`/`B` with no majority —
the same case whose `0.5` first draw decides its label at the threshold, per
`design-notes.md` §10.

The local judge is the outlier on this axis too, and worse here than pointwise:
`0.571` over the 7 pairs it could answer, 14 pairs with no majority under either
order, and 7 unparseable draws. Its `framing-sensitive` flag understates it — on
the pairwise protocol it is both unreliable and order-dependent.

## Reproduce it

The published table is rebuilt offline from the stored artifact, which needs no API
key and no six-hour run. The artifact is attached to the [v0.1.0
release](https://github.com/ivander08/id-eval/releases/tag/v0.1.0) rather than
committed — it is 2.1 MB and a diagnostic artifact, not a published dataset:

```bash
curl -LO https://github.com/ivander08/id-eval/releases/download/v0.1.0/results_calibration.json
```

Then rebuild the table:

```bash
python scripts/replay_calibration.py \
  --artifact results_calibration.json \
  --labels annotations/rubric_labels.jsonl \
  --max-drift 3 \
  --out README_table.md            # then paste between the README markers
```

Without `--match-audit` it asserts that recomputing `gt` from each row's stored
`output` and `expected` reproduces the stored `gt` on all 888 scoreable rows, and
exits non-zero otherwise. `--max-drift 3` is not optional here: the intra-word
joiner fix (`design-notes.md` §11.4) changed what the matcher returns for
`tydiqa-019` on one subject, so 3 of the 888 rows recompute to `1.0` against a
stored `0.0` by design. The flag bounds that to exactly those three; a fourth would
still fail. `--verify-readme README.md` checks the rebuilt rows against the
committed table row for row. The labels themselves are reviewed through
a worksheet, so a pass can be re-run or extended without re-reading the artifact:

```bash
python scripts/label_review.py emit          # -> annotations/review_worksheet.md
python scripts/label_review.py apply --decisions annotations/review_decisions.jsonl
```

`emit` renders one section per (suite, case, subject) from the stored artifact —
prompt, rubric note, draft label with its rationale, and the response, truncating
only `cmx-015`'s 88k-character repetition loop. `apply` is the only writer: it
validates each decision against the same rules `load_labels` uses, keeps the
provenance header byte for byte, leaves undecided rows at `draft:assistant`, and
writes in place through a temp file + `os.replace`. A full live run is still what
produced the judge verdicts in the first place:

```bash
export OPENAI_API_KEY=...        # the kenari provider reuses this variable
ideval calibrate \
  --suite factual --suite factual_indommlu --suite factual_tydiqa \
  --suite cultural --suite register --suite codemix \
  --subject kenari/qwen3-8-flash --subject ollama/qwen2.5:1.5b \
  --judge kenari/deepseek-v4-1-flash --judge kenari/glm-5-3-flash \
  --judge ollama/qwen2.5:1.5b \
  --annotations annotations/rubric_labels.jsonl \
  --repeats 3 --out results_calibration.json
```

`--repeats 3` across all six suites takes roughly six hours, which is why the table
is regenerated by hand and never in CI. The scheduled CI job runs a smoke
calibration (`--repeats 1`, two suites) to prove the pipeline still works; it does
not touch the published numbers.

The pairwise probe is a separate, bounded run:

```bash
python scripts/pairwise_probe.py \
  --artifact results_calibration.json --suite factual --repeats 2 \
  --out results_pairwise.json
```

`results_calibration.json` and `results_pairwise.json` match `results*.json` in
`.gitignore`, so they are not committed: `results_calibration.json` ships as a
[v0.1.0 release
asset](https://github.com/ivander08/id-eval/releases/download/v0.1.0/results_calibration.json)
and `results_pairwise.json` is regenerated by the probe above. The README table is
the artifact of record; the pair rows inside the JSON are what the disagreement
analyses in `design-notes.md` §6 are computed from.

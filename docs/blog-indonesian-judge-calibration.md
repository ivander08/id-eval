# Nobody has published a kappa for a Bahasa Indonesia judge

LLM-as-a-judge is the default scoring path for open-ended generation, and the
judges are tuned on English. Ask for the agreement number of a judge on Bahasa
Indonesia and there is nothing to quote. That absence is the reason `id-eval`
exists, and this is what came out of measuring it.

The measurement: 248 cases across six suites, two subjects
(`kenari/qwen3-8-flash`, `ollama/qwen2.5:1.5b`), three judges
(`kenari/deepseek-v4-1-flash`, `kenari/glm-5-3-flash`, `ollama/qwen2.5:1.5b`),
every case judged three times with the rubric's position alternated, producing 36
rows and 1464 pair rows. The full table is in the [README](../README.md#the-calibration-study-m2);
the method is in the [study write-up](calibration-study.md).

The headline is not that the judges disagree. It is that the instrument broke
first, that the reliability axis found the real problem, and that the fix I
expected to work made the numbers worse in a way I could measure.

## The instrument failed, not the judges

Two rows from the shipped table:

| judge | subject | suite | n | po | kappa | pabak |
|---|---|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | `kenari/qwen3-8-flash` | factual | 32 | 0.969 | **0.000** | 0.938 |
| `kenari/glm-5-3-flash` | `kenari/qwen3-8-flash` | factual_tydiqa | 40 | 0.925 | **−0.034** | 0.850 |

The first judge agreed with ground truth 31 times out of 32 and is reported as
`kappa = 0.000`. The second agreed 37 times out of 40 and is reported as a
*negative* kappa. Read only the kappa column and both judges look worthless, or
worse than worthless.

The mechanism is prevalence. On `factual / kenari/qwen3-8-flash` the ground truth
pass rate is `0.938`, so chance agreement `pe` is `0.938` as well; with
`po = 0.969`, kappa is `(0.969 − 0.938) / (1 − 0.938) ≈ 0.000`. The suite is easy
enough for the subject that almost everything passes, and when almost everything
passes, chance agreement is already near one and kappa has almost no room left to
reward actual agreement.

What makes this worth writing down is the direction the correction moved things.
Fixing the matcher's tokenization raised the pass rate further. `po` went **up**,
and kappa went **down**, because `pe` rose faster. The paradox got worse precisely
because the instrument got better. A judge-versus-truth study on an easy suite
will report this, and the honest reading is not "these judges are bad" but "kappa
is the wrong statistic for a skewed ground truth".

`pabak = 2·po − 1` carries no prevalence term. On those two rows it reads `0.938`
and `0.850` — which is what the raw agreement actually says. `prevalence` fires on
**11 of 36 rows**, so this is not two unlucky cells; it is a structural property of
the suites. The flag exists so a reader can see which kappas cannot be read at face
value, and the table publishes both numbers rather than picking the flattering one.

## A judge that cannot agree with itself

The second half of Norman et al.'s protocol — test-retest reliability — is the part
a single-pass study cannot see, and it is where the local judge fell apart.

| judge | rows | retest | frame | draws failed |
|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | 12 | 0.979 | 0.953 | 0 / 1464 |
| `kenari/glm-5-3-flash` | 12 | 0.990 | 0.981 | 0 / 1464 |
| `ollama/qwen2.5:1.5b` | 12 | 0.833 | 0.575 | 108 / 1464 (7.4%) |

`retest` is the mean share of draws agreeing with their item's majority label;
`frame` is how often the two framings — rubric first versus response first — reach
the same majority verdict. The API judges are near-perfect on both. The local judge
scores `0.833` on test-retest and `0.575` on framing: moving the rubric around a
single unchanged response flips its majority verdict almost half the time.

The 108 failed draws are the other half of the story, and they are invisible in the
`err` column, which reads `0` for the local judge on every row. That is not a bug:
`errors` counts *cases*, and a case counts as an error only when *every* draw
failed to parse. A judge that fails one draw in three and gets the other two right
never registers. (The eight cases it does not score on `factual_indommlu` are
subject failures, published as `subj_err`.) Per-draw failure is visible only
because `--repeats 3` counts draws, and 7.4% of 1464 draws is 108 pieces of evidence
that the single-pass number for this judge was noise.

This is why `ideval calibrate --repeats 1` now prints a notice. On a single pass
`retest` and `frame` render `-`, and the reliability axis — the only axis on which
the local judge's problem is visible at all — silently disappears. The default
stays at 1, because a default of 3 triples every judge call and would make the CI
smoke job three times slower for no coverage gain, but a reader who does not know
what they are missing will not ask for it.

## A fix I measured and threw away

The exact-match matcher still cannot see paraphrase: a correct answer phrased
differently scores zero. The obvious fix is an affix-aware token matcher, since
Indonesian is heavily affixed and `berlari` / `berjalan` share a root. Strip the
affix set (`meN-`/`men-`/`mem-`/`ber-`/`ter-`/`di-`/`pe-`, `-kan`/`-nya`/`-an`/`-i`)
from both sides and require every stripped expected token to be present in the
stripped output set.

I implemented it and audited it against the stored artifact. It moved 9 pair rows
from a stored `0.0` to `1.0` across three cases. Six of those nine were **false
positives** — wrong answers scored as correct:

- `tydiqa-015` expects `keriting merah`. The response offers *green* curly chilis
  (`Cabe Keriting Hijau`) and mentions `merah` somewhere else in the paragraph.
  Bag-of-words containment passes; the answer is wrong.
- `tydiqa-022` expects `agama Jawa`. The response says `bahasa Jawa`. Flipped to
  `1.0`.

Two mechanisms made it fail, and both are worth recording because the idea is
attractive enough to be re-proposed. First, bag-of-words containment discards word
order and adjacency: substring containment at least required the expected phrase to
appear contiguously, but a token set does not, so `agama` and `Jawa` anywhere in a
long response is enough. Second, the affix strip is not a stemmer. A minimum-stem
guard blocked the shortest stems but not the wrong ones — `merah → rah`,
`pertama → rtama`, `berjalan → jal`.

The criterion was declared before the experiment: any non-zero false-positive count
reverts the change. So the matcher is not in the code, and the one case that flipped
correctly (`tydiqa-025`, a right answer broken by tokenization) went back to
scoring zero. The gap stays open, and the plan for closing it is a semantic matcher
or different ground truth — not a wider regex. Recording the reverted experiment is
more useful than the experiment itself, because the next person to have this idea
will have it for the same good reason.

## What this still gets wrong

- **The 192 rubric labels are machine-authored, drafted and reviewed.** `cultural`,
  `register` and `codemix` have no `expected` value, so they were originally
  calibrated judge-against-judge. `annotations/rubric_labels.jsonl` supplies a
  `0.0`/`0.5`/`1.0` label per (suite, case, subject), and every row's `rater` field
  reads `review:assistant`: a drafting pass followed by a second pass that re-read
  each response against its suite's rubric. That review changed **4 labels**. It is
  a real second reading, but it is another model reading the same drafts, so it
  shares the first pass's blind spots in a way an independent human rater would not.
  The labels are the single point of failure for those rows, and `review:<name>` for
  a human remains the open hook.
- **`prevalence` fires on 11 of 36 rows.** Growing the suites fixed `low-n` — every
  row now carries `n >= 32` — but no amount of growth fixes a skewed ground truth.
  Difficulty is a property of the subject–item pair, not of the item.
- **The paraphrase gap is still open**, as described above.
- **The published table is an offline replay, not a fresh run.** It was rebuilt from
  the stored `results_calibration.json`, because `adapters.chat` pins no
  temperature: a fresh run would judge different text and every number would move
  for reasons unrelated to any change under test. The judge verdicts are the
  original study's; only the ground-truth column for the rubric rows is new.

## Reproduce it

The table needs no API key and no six-hour run. The stored artifact is a 2.1 MB
[v0.1.0 release
asset](https://github.com/ivander08/id-eval/releases/download/v0.1.0/results_calibration.json):

```bash
curl -LO https://github.com/ivander08/id-eval/releases/download/v0.1.0/results_calibration.json
```

```bash
python scripts/replay_calibration.py \
  --artifact results_calibration.json \
  --labels annotations/rubric_labels.jsonl \
  --max-drift 3 \
  --out README_table.md            # then paste between the README markers
```

`--max-drift 3` is required, not cosmetic: the joiner fix described above changed
what the matcher returns for `tydiqa-019` on one subject, so 3 of the 888 scoreable
rows legitimately recompute to `1.0` against a stored `0.0`. Without the flag the
script refuses to rebuild at all and tells you the count.

Without `--match-audit` it asserts that recomputing `gt` from each row's stored
`output` and `expected` reproduces the stored `gt` on all 888 scoreable rows, and
exits non-zero otherwise. The labels themselves are reviewed through a worksheet:

```bash
python scripts/label_review.py emit          # -> annotations/review_worksheet.md
python scripts/label_review.py apply --decisions annotations/review_decisions.jsonl
```

A full live run is still what produced the judge verdicts in the first place:

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

## Where to read more

- [`docs/calibration-study.md`](calibration-study.md) — the full method, the
  pairwise position-bias probe, and the per-row detail behind every claim here.
- [`docs/design-notes.md`](design-notes.md) — why each choice was made, what it
  costs, and the published evidence behind it. §8 is what the study knew it got
  wrong; §11 is what has since been closed and what has not.
- [`README.md`](../README.md#the-calibration-study-m2) — the 36-row table this post
  reads from, with the `flags` column that marks the cells that cannot be taken at
  face value.

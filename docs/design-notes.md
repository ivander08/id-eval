# Design notes: what id-eval does differently

Most eval harnesses report a percentage. This document records the specific,
non-obvious choices id-eval makes instead — why each one exists, what it costs,
and where the practice is backed by published evidence. It also records what we
know we still get wrong.

Everything below is grounded in this repository's code and in the sources listed
at the end.

---

## 1. Ground truth is a pipeline, not a rubric

`src/ideval/schema.py` — `TestCase.ground_truth_type` is a closed union:

| type | scoring path | who decides |
|---|---|---|
| `exact` | normalized containment against `expected` | the matcher |
| `choice` | last standalone uppercase A–E in the output | the matcher |
| `rubric` | LLM judge against a suite rubric | the judge |

The point is that **the scoring path is declared per case, not per suite**. A
suite is not "an LLM-judged suite"; each case says how it must be scored, and
`TestCase.scoreable` derives from that declaration rather than from a convention.

This matters because the alternative — one scoring function per benchmark — makes
it impossible to state, in the artifact, which cases were decided by a matcher and
which by a model. When the two disagree, you need to know which is which. See §4.

### The `choice` matcher is deliberately case-sensitive

`runner._match_choice` takes the *last standalone uppercase* letter A–E, and
`_CHOICE = re.compile(r"(?:^|\W)([A-E])(?=[\W_]|$)")` excludes lowercase.

The reason is Indonesian-specific: a bare lowercase `a` is an ordinary word, not an
answer letter. A case-insensitive matcher would read "Kalimat **a** ini tentang
Benda" as answer `A`. There is a regression test pinning exactly this
(`test_match_choice_is_case_sensitive`).

### Adversarial cases that test the judge, not the model

`judge_only: true` cases embed their response in `input` and skip the subject
model entirely. All three rubric suites ship one:

| case | what it embeds |
|---|---|
| `cult-018` | Ramadan described as a 3-day festival with no sahur/iftar, plus fireworks |
| `reg-018` | a formal letter request answered in heavy Jakarta slang and English |
| `cmx-018` | an Indonesian–English code-mixed request answered in pure formal English |

Each carries `reference_note: "ADVERSARIAL: ... should score LOW"`. These are
judge canaries: a judge that scores them high is not measuring what the rubric
claims. Most harnesses test only the subject; these test the instrument.

---

## 2. Reference-aware judging

`src/ideval/metrics/factual.py` interpolates the gold answer into the judge prompt:

```
Reference answer: {reference}

Score 1.0 if the response states the reference answer or an unambiguous
equivalent. Score 0.0 if it states something different, contradicts the
reference, or answers a different question.
```

A judge that cannot see the reference grades **plausibility**, not correctness. It
has no way to distinguish "confidently stated and true" from "confidently stated".
Supplying the reference converts the judge from an open-ended quality rater into a
comparison operator, which is the only form in which judge-vs-ground-truth
agreement is even a meaningful quantity to compute.

This is what makes the calibration study in §4 possible at all.

---

## 3. Judge failures are evidence, not noise

`EvalResult` carries four separate judge fields:

```python
judge_score: float | None = None   # the parsed verdict (first successful draw)
judge_reason: str | None = None    # the judge's stated rationale for judge_score
judge_raw: str | None = None       # raw judge text, set ONLY when parsing failed
judge_repeats: list[float] = []    # every successful draw, in order
```

`runner._judge` returns `tuple[JudgeVerdict | None, str]`, so the raw text survives
a parse failure instead of being discarded. The two failure modes stay
distinguishable and are documented in the docstring:

- `raw == ""` → the API call raised. An infrastructure problem.
- `raw != ""` with a `None` verdict → the model answered, but not in the contract
  format. A model problem.

Collapsing those two into a single `errors` counter, as most harnesses do, throws
away the only evidence that tells you which one you have. A judge failure rate of
either kind is a retry-policy question or a prompt-contract question, and you
cannot tell which without the raw text. In the shipped study the local judge fails
to parse **7.4% of individual draws** while both API judges fail **none** —
visible only because `--repeats 3` counts draws rather than cases. `errors` counts
*cases*, not draws: a case is an error only when every draw failed, so the `err`
column reads `0` for the local judge on every row despite a 7.4% per-draw failure
rate. The `errors` column that the previous single-pass study published could not
have shown this, and the two API judges' zero-error rows are the reason the column
was trusted too far.

The rationale is also captured per row, because a judge's stated reason is the
audit trail for its score. `score_with_judge` resets `judge_reason` and
`judge_raw` before every judge pass, for the same reason it resets `judge_score`:
otherwise a failing judge silently inherits the previous judge's rationale. There
is a regression test for that inheritance specifically.

---

## 4. Cohen's kappa alone is not an agreement report

`src/ideval/calibrate.py` computes `po` (observed agreement), `pe` (chance
agreement), `kappa`, and `pabak` — and reports all four. With `--repeats > 1` it
adds `test_retest` and `framing_agreement` (§5), so a row carries both axes of
Norman et al.'s protocol rather than only the validity one.

### Two axes, one table

A suite whose cases are all `rubric` has no numeric ground truth, so there is
nothing to score a judge against. `run_calibration` detects that (`not any(c.scoreable
for c in cases)`) and emits **one row per judge pair** instead of one row per
judge: `build_inter_judge_report(judge, judge_b, ...)` compares two judges over
the same subject outputs.

The two row kinds share `CalibrationReport`, distinguished by `judge_b`:
empty means judge-vs-ground-truth, non-empty names the judge compared against.
The `vs` column renders `truth` or the opponent, unconditionally, so a table can
never be misread as all-one-axis and two runs stay diffable. Precision/recall on
a pair row read as "how often this judge's passes are also the other's".

Three choices worth recording. Pairs are generated with `judges[i+1:]`, so a judge
is never compared against itself — that would report a trivial `kappa = 1.0`.
`self-judge` fires when the subject is *either* side of the pair, because the pair
is confounded by self-preference bias regardless of which side the subject sits
on. And the stability columns are the mean of the two judges' own values rather
than a pooled figure: pooling two judges' draws would mix items and describe
neither judge. Each judge's raw draws stay on the pair rows, so either can be
recomputed.

A rubric suite run with fewer than two judges emits no rows and prints a warning.
That is intended — with one judge there is no comparison, and no ground truth to
fall back on.

The reason is a published and common failure mode. On a near-constant ground
truth, `pe` approaches 1, and kappa collapses toward zero **no matter how well the
judge agrees**. From the shipped study:

| judge | subject | suite | n | po | kappa | pabak | flags |
|---|---|---|---:|---:|---:|---:|---|
| `kenari/deepseek-v4-1-flash` | `kenari/qwen3-8-flash` | factual | 32 | 0.969 | **0.000** | 0.938 | prevalence |
| `kenari/glm-5-3-flash` | `kenari/qwen3-8-flash` | factual_tydiqa | 40 | 0.900 | **−0.039** | 0.800 | prevalence |

Both rows are real output. The first is a judge that agreed with ground truth 31
times out of 32 and is reported as `kappa = 0.000`; the second agreed 36 times out
of 40 and is reported as a *negative* kappa. A reader given only the kappa column
would conclude both judges are worthless, or worse than worthless. They are not —
the ground truth is skewed and kappa is the wrong instrument for those cells.
`pabak = 2·po − 1` carries no prevalence term and stays readable there.

`agreement_terms` is the shared implementation; `cohens_kappa` delegates to it
rather than duplicating the formula, so the three existing kappa tests
(`test_kappa_known_value`, `test_kappa_perfect_agreement`,
`test_kappa_mismatched_lengths`) guard both statistics at once.

`test_pabak_exposes_what_kappa_hides` pins the degenerate cell that motivated the
statistic: on the original 10-case `factual` artifact, `kappa == 0.0` and
`pabak == 0.8` on the same ten observations. That cell no longer exists — the
suite now has 32 cases — but the coefficient still collapses on the 32-case cell
above, so the test's ten-observation fixture stays as the minimal reproduction.

### Limits of this choice

PABAK removes prevalence **and** bias, so it reads optimistically — it is not a
strictly better kappa. The literature's other candidate is Gwet's AC1, which is
more conservative (on the `factual_tydiqa` cell above, `po = 0.900`,
`pe_AC1 = 0.095`, `AC1 = 0.890` against `pabak = 0.800`; on the 32-case `factual`
cell the two agree closely, `AC1 = 0.968` against `pabak = 0.938`). We report
PABAK and the raw agreement terms rather than a single number, on the principle
that a reader should be able to recompute either coefficient from what we
publish. See §8.

---

## 5. Fragile cells are annotated, not just computed

`_flags` marks five conditions that make a row hard to read:

| flag | trigger | why |
|---|---|---|
| `low-n` | `n < 30` | one flipped case moves kappa by ~0.1 or more |
| `prevalence` | `pe >= 0.80` | kappa is prevalence-dominated in this cell |
| `self-judge` | `subject == judge` | self-preference bias confounds the row |
| `unstable` | `test_retest < 0.90` | the judge does not agree with itself run to run |
| `framing-sensitive` | `framing_agreement < 0.80` | moving the rubric changes the verdict |

The `low-n` threshold is a power argument, not a convention. For a proportion,
`SE = N^(−1/2)·√(p(1−p))`; at `n = 10, p = 0.6` that is `±0.30` at 95%, and a
single flipped case swings kappa by `0.20`. At `n = 300` the same flip moves it by
`0.007`. A table that prints `n = 10` and `kappa = 0.800` with equal visual weight
to `n = 80` is not reporting uncertainty. The shipped study no longer contains a
row below `n = 32`: the four hand-authored suites were grown to 32 cases each, so
the flag is carried for future suites rather than fired by this one. The threshold
was not moved to meet the data.

The `self-judge` flag is the most important flag in the table. Panickssery et al. show
that LLM evaluators recognise and favour their own generations, with the strength
of the bias tracking self-recognition capability — so a row where subject and
judge are the same model is confounded by construction. The shipped study has
nine such rows, all marked, and five of them are additionally `unstable` and
`framing-sensitive` — the local judge is both the most biased and the least
self-consistent row in the table.

`unstable` and `framing-sensitive` are the two flags that only exist when
`--repeats > 1`. They are the operational form of Norman et al.'s consistency–
validity orthogonality: a row can agree with ground truth perfectly and still be
flagged `unstable`, and that combination is the one worth reading first.

### What the repeats measured

Three draws per case, rubric position alternating, across 488 case–subject pairs
per judge (the six suites' cases crossed with the two subjects, minus the 8
`factual_indommlu` cells the `kenari` subject errored on):

| judge | `test_retest` | `framing_agreement` | draws disagreeing | per-draw parse failure |
|---|---:|---:|---:|---:|
| `kenari/glm-5-3-flash` | 0.991 | 0.984 | 32.2% | 0.0% |
| `kenari/deepseek-v4-1-flash` | 0.978 | 0.949 | 35.9% | 0.0% |
| `ollama/qwen2.5:1.5b` | 0.823 | 0.555 | 77.0% | 7.4% |

Three things follow, none of which the single-pass table could show.

**Stability separates the judges, and it separates them the right way.** The local
judge sits `0.16` below both API judges on `test_retest` — far outside the `0.02`
that would indicate the draws were not independent. That is the falsification
test for the statistic itself: if a stability number cannot pick out the judge
that fails 7.4% of draws and flips its verdict on 77% of cases, it is measuring
nothing. Note that neither API judge failed a single draw, so the `err` column
alone would have hidden this entirely.

**Agreement and stability are orthogonal here, exactly as Norman et al. claim.**
`kenari/glm-5-3-flash` on `factual_indommlu / ollama` posts `kappa = 0.968` *and*
`test_retest = 0.996` with zero flags. `kenari/deepseek-v4-1-flash` on
`factual_tydiqa / kenari` posts `kappa = −0.094` — but that row is stable
(`0.975`), while the local judge's `factual / kenari` row has `kappa = 0.090` and
is *not* (`0.790`, `unstable`). Two rows a reader would previously have ranked
identically are now distinguishable.

**Framing sensitivity is the sharper instrument, and it catches the boundary
cases.** The local judge's framing agreement (`0.555`) is worse than its
test-retest (`0.823`) by a wide margin: it is not just noisy run to run, it
*systematically* answers differently depending on whether the rubric precedes or
follows the response. The API judges lose far less (`0.984`, `0.949`). That is the
pointwise analogue of position bias showing up as a measurable, judge-specific
effect rather than a suspicion — see §8.

Five of the nine `self-judge` rows are simultaneously `unstable` *and*
`framing-sensitive`; the other four carry `framing-sensitive` alone. The §8
caveat that these rows are "confounded by construction" is now quantified rather
than asserted.

---

## 6. The artifact is auditable without a join

`run_calibration` writes one row per (suite, subject, judge, case) carrying
`expected`, `output` and the judge's `reason` inline:

```python
{"suite", "subject", "judge", "case_id", "gt", "judge_score", "judge_scores",
 "expected", "output", "reason"}
```

`gt` is `null` on rubric rows, where the judge's verdict is the only score in
play; `judge_score` carries that verdict either way, so the field keeps one
meaning across both row kinds: what the judge said.

This is a deliberate denormalisation. `results_calibration.json` is a gitignored
diagnostic artifact, not a published dataset, so the cost of repeating each
subject output once per judge is irrelevant — and the benefit is that **any
disagreement in the table can be read directly out of the file** without
regenerating outputs or joining against a side table.

That property is what turned the largest disagreement in the study from an
unexplained number into a finding. Before the normalizer fix, filtering
`gt == 0.0 and judge_score >= 0.5` on `factual_tydiqa / kenari/qwen3-8-flash`
yielded 22 rows over 9 distinct cases, and the inline `expected` / `output` /
`reason` triples classified every one of them:

| cause | cases | example |
|---|---:|---|
| valid paraphrase, judge correct | 5 | `berjalan pada kecepatan supersonik` vs *"berlari lebih cepat dari suara"* |
| normalizer gap — unit alias | 1 | `25 ha` vs `25 hektare` |
| normalizer gap — unit language | 1 | `20,779 square kilometres` vs `20.779 kilometer persegi` |
| normalizer gap — superscript | 1 | `637.657 km2` vs `637.657 km²` (`²` is `\w`, so it survives punctuation stripping) |
| judge partially crediting a wrong answer | 1 | `1889` vs `1892`, scored `0.5` |

The dominant cause is not a wrong judge — it is exact-match strictness on
paraphrase, which is exactly the effect Ho et al. quantify (EM correlates `0.17`
with human judgment on extractive QA, versus `0.85` for a judge).

Note what is *not* a cause: digit separators. `_PUNCT` strips both `.` and `,`, so
`20,779` and `20.779` both normalize to `20 779` and always matched. An earlier
draft of this section claimed otherwise; re-running the classifier against the
real `_match_exact` rather than a hand-written approximation is what caught it.

### The three normalizer gaps are now fixed

`_normalize` translates superscript digits and canonicalizes square-kilometre and
hectare aliases (`km²`, `km2`, `square kilometres`, `kilometer persegi`,
`hektare`, `ha`), so all three gap rows above match. The blast radius was measured
before the change was accepted, on the artifact that found them: **5 of 80**
`factual_tydiqa` rows flip, confined to three case ids, and every non-tydiqa
kappa is unchanged to three decimals. On the re-run artifact the same three case
ids account for 18 of 1464 pair rows, and the `expected` string now appears in the
output on all 18 — but only 3 of the 18 still disagree, because the judge also
credits them. Closing the matcher gap moved those rows out of the disagreement
set; whether they stay there is now a judge question, not a matcher question.

The three regexes are the minimum set that closes the measured gaps; adding more
units would widen the false-match surface for no corpus benefit.
`test_normalize_still_rejects_genuine_misses` is the guard on that widening.

After the fix the disagreement set on that cell is **7 rows over 7 distinct
cases**, and the classifier splits it two ways. Three are the paraphrase case:
the judge credited a correct answer the matcher rejects by construction — `Genin`
for *"ninja kelas rendah yang hanya menjalankan misi kelas D"*,
`kecepatan berlari supersonik` for *"berjalan pada kecepatan supersonik"*. Those
stay wrong on purpose: fixing them needs a semantic matcher or a different ground
truth, not a wider regex, and Ho et al. already quantify the cost of exact match
on extractive QA.

The other four are the reverse and are **judge misses, not matcher failures**: the
`expected` string appears verbatim in the output and the matcher scores it `1.0`,
while the judge returns `0.0`. `tydiqa-010` is the clearest — the output reads
*"Lecce terletak di wilayah Puglia (Apulia), bagian selatan **Italia**"* and the
judge's stated reason is that the response "does not explicitly state Italy as the
country". A reference-aware judge given `Italia` in its prompt missed `Italia` in
the response. That is the failure mode §2 exists to prevent, and it is only
visible because the pair rows carry `expected`, `output` and `reason` inline
(§6). It is also why this cell's kappa is *negative* while `pabak = 0.650`: the
matcher is right four more times than the judge is.

**The fix moved agreement up and kappa down, which is not a contradiction.**
On `factual_tydiqa / kenari/qwen3-8-flash / kenari/deepseek-v4-1-flash`, `po` rose
`0.775 → 0.825` across the fix and the re-run, while kappa fell `0.217 → −0.094`.
Correcting the matcher raised the ground-truth pass rate to `0.925`, which raises
chance agreement to `0.837` and deflates kappa past zero — the §4 prevalence
effect, now firing harder because the ground truth is *more* skewed than before.
A kappa of `−0.094` alongside `po = 0.825` is the single least readable row in the
study, and it is entirely an artifact of prevalence. PABAK, which carries no
prevalence term, sits at `0.650` and tracks the raw agreement. This is the
clearest instance in the study of why kappa alone is not an agreement report.

**One consequence worth flagging:** a half-point verdict sits exactly on the
binarization threshold, where it decides the pass/fail label. In the shipped
artifact 134 of 1464 pair rows carry at least one draw at exactly `0.5`, and 57
rows publish `judge_score == 0.5`. That is a real source of instability in the
kappa column. It is no longer unmeasured — `test_retest` counts a draw as a pass
at `>= 0.5`, so a judge that lands on the boundary run to run shows up as
instability — but the threshold itself remains a convention, not a finding.

---

## 7. Reproducibility choices, and their cost

**No temperature pinning.** `adapters.chat` sends no `temperature`, deliberately:
`temp=0` stalls `qwen2.5` on Ollama 0.34, and per-provider defaults are the only
setting that runs everywhere. This costs run-to-run determinism. It is also
defensible on the evidence: Haldar & Hockenmaier find that forcing deterministic
sampling *degrades* agreement with human judgment, and that majority-voting over
several runs beats both a single sample and a no-sampling run. Determinism and
validity trade against each other here; we chose validity and recorded why.

**No retry or repair logic for the local judge.** When a judge returns text that
does not parse, id-eval records it and moves on. It does not retry, and it does
not attempt to salvage a score from malformed output. Silently repairing judge
output is how a harness starts inventing data.

**Failures are counted, not dropped.** `n + errors` equals the suite's case count
for every row, so a row can never quietly be computed over a subset. The `err`
column is part of the table for the same reason.

**Repeats are a study parameter, not a default.** `calibrate --repeats N` judges
each case `N` times, alternating prompt framing, and records every draw on the
pair row (`judge_scores`) beside the first successful one (`judge_score`). The
table then carries `retest` and `frame`. The reason not to make it the default is
cost, not principle: `--repeats 3` triples judge calls, and a single-pass run is
still the right tool for a quick diagnostic — it renders both columns `-` rather
than pretending to a stability number it did not measure.

Two consequences worth stating. A case counts as an error only when *every* draw
failed, so `n + errors` still equals the case count and a judge that fails once in
three draws is not silently dropped from the row. And `test_retest` can be `1.0`
on a case that fails under every draw, because only successful draws enter the
statistic — stability of failure is still stability. Coverage is what `n` and
`errors` report; stability is a separate axis.

---

## 8. What we know we get wrong

Recording this is the point of the document — a design note that only lists
strengths is marketing.

1. **The rubric suites have no numeric ground truth.** `cultural`, `register` and
   `codemix` — 96 cases — declare `ground_truth_type: rubric` and carry no
   `expected` value, so there is nothing to score a judge against. They are now
   calibrated on a different axis: **inter-judge agreement**, one row per judge
   pair, reported with the same kappa/PABAK/stability columns as the factual rows
   and labelled `vs <judge>` in the `vs` column so a reader cannot mistake them
   for judge-vs-truth. What remains wrong is the axis itself — two judges agreeing
   says nothing about whether either is correct, and the multilingual-judge
   literature is unambiguous that reliability is language-conditional
   (Doğruöz et al.; Fu & Liu report mean Fleiss' κ ≈ 0.3 across 25 languages).
   Authoring `expected` values for these 96 cases is the only way to close it,
   and the labels would themselves be a single rater's judgment — the exact
   reliability problem being measured.

   The inter-judge result is worth stating plainly. Across the 18 rubric pair
   rows, the two API judges agree with each other at a mean `kappa = 0.531` over
   the four rows where kappa is defined (`test_retest = 0.980`,
   `framing_agreement = 0.964`; the other two rows have `pe = 1.0`, where kappa is
   undefined rather than zero), while any pair containing the local judge sits at
   a mean `kappa = 0.015` (`0.924`, `0.798`). Four pairs are `unstable` and six
   are `framing-sensitive` — every one of them a pair with the local judge.

   Four of those 18 pairs are also `prevalence`, which is the honest reading of
   the rubric suites' ceiling. On `codemix / kenari` the two API judges pass 31
   and 30 of 32 cases, so `pe = 0.94` and their `kappa = 0.652` understates an
   agreement of `0.969`; on `cultural / ollama` and `register / ollama` every API
   judge passes 0 of 32, so `pe = 1.0` and kappa is undefined rather than zero.
   Those suites need *harder* cases, not more of them.

2. **Pairwise position bias is unmeasured.** `_judge` presents a single response
   against a rubric, so pairwise position bias does not apply directly. The
   pointwise analogue is now measured: with `--repeats > 1` the rubric alternates
   between after the response (variant 0) and before it (variant 1), and
   `framing_agreement` reports how often the two framings reach the same
   majority verdict. What is still untested is the pairwise form — two responses,
   order swapped — which needs a different judge contract (Shi et al.).

3. **Test-retest reliability is measured, but only where `--repeats > 1`.** The
   study's published rows carry `test_retest`, the mean share of draws agreeing
   with their item's majority label. Norman et al.'s central result is that
   consistency and validity are *orthogonal* — a judge can be perfectly
   reproducible and maximally biased — so the two axes are reported side by side
   rather than collapsed. The remaining gap is that `--repeats` is a study
   parameter, not a default: a single-pass run leaves both columns `-`.

4. **The exact-match normalizer still cannot see paraphrase.** The three measured
   gaps (unit aliases, unit language, superscript exponents) are fixed in
   `_normalize`. What remains splits two ways. Three of the seven disagreements on
   the worst cell are the paraphrase case — a valid answer exact match rejects by
   construction. The other four are the opposite, and are the more useful finding:
   the `expected` string appears verbatim in the output, the matcher scores it
   `1.0`, and the judge returns `0.0`. `_normalize` is SQuAD-style plus unit
   canonicalization; it does not canonicalize scripts or Indonesian affixes, and
   closing the paraphrase gap needs a semantic matcher, not a wider regex. Closing
   the judge-miss gap needs nothing from the matcher at all — it is a §2 failure,
   visible only because the pair rows carry `expected`, `output` and `reason`
   inline.

5. **`prevalence` cells are still published.** `low-n` is gone: the four
   hand-authored suites were grown to 32 cases each, so all 36 rows now carry
   `n >= 32` and no row is flagged for sample size. What replaces it as the
   dominant caveat is `prevalence` — 10 of 36 rows. That is the honest limit of
   what growing a suite can fix. The `factual` suite is the clearest case: the 22
   new cases were written to be *harder* — multi-word and numeric answers rather
   than one-word capitals — and they are harder for the small local subject
   (`5/22` passed, against `6/10` on the old cases), but the API subject answers
   all 22 correctly, so the suite pass rate rises `0.900 → 0.969` and kappa stays
   pinned at `0.000` even though `po` improved `0.900 → 0.969`. `low-n` was a
   coverage problem and is fixed; `prevalence` is a difficulty problem, and
   difficulty is a property of the *subject–item* pair, not of the item alone.

---

## 9. The GEval backend is opt-in, and what that cost

`src/ideval/metrics/deepeval_backend.py` — `--judge-backend deepeval` routes
judging through deepeval's `GEval` metric instead of the native JSON-contract
prompt. It is **not** the default, and that is a deliberate choice with a price
attached.

### Why opt-in rather than the default

The published 36-row table in the README is the artifact of record, and it was
produced by the native path over a `--repeats 3` run across all six suites that
cost roughly six hours. Making `GEval` the default would silently change what
every number in that table means, and the table could not be republished without
paying that six hours again. So the backend is opt-in: the published table stays
valid, and the `GEval` path is validated by a bounded parity sample instead. That
is a real cost — two judge implementations now exist and must agree — and it is
the honest alternative to quietly invalidating a published artifact.

### `RepoJudge` exists because `GEval` cannot reach these endpoints

`GEval(model=None)` constructs an `OpenAIModel` and raises
`DeepEvalError: OpenAI API key is not configured`. deepeval's bundled
`OllamaModel` is not a workaround either: it requires the `ollama` package, which
is not installed, and it defaults `temperature=0.0`, which `adapters.chat`
deliberately avoids because temp=0 stalls `qwen2.5` on Ollama 0.34 (§7).

`RepoJudge` is a `DeepEvalBaseLLM` subclass that delegates to `adapters.chat`, so
the deepeval path inherits provider routing, the no-temperature-pinning policy,
and the kenari/ollama base_urls rather than reimplementing them. One detail is
load-bearing: `DeepEvalBaseLLM.__init__` calls `self.load_model()`
(`deepeval/models/base_model.py:64`), so the client slot must be initialised
before `super().__init__` runs. The judge is built **once per model** and reused
across cases — constructing it per case would rebuild the underlying OpenAI client
32-248 times per run.

### `Rubric(score_range=(0, 1))` is mandatory, not cosmetic

`GEval`'s default score range is `(0, 10)`, and `measure` normalizes the raw
verdict into `[0, 1]` by `(score - lo) / (hi - lo)`. A judge answering `0.8`
under the default range is therefore reported as `0.08` — measured on this repo,
not inferred. Passing `rubric=[Rubric(score_range=(0, 1), expected_outcome=...)]`
sets `GEval.score_range == (0, 1)`, the span becomes 1, and the verdict passes
through unchanged. The field is `expected_outcome`, not `expected_output`.
`test_deepeval_backend_scores_on_the_repo_scale` pins this: it asserts a fixed
`0.8` payload yields `JudgeVerdict(score=0.8)`, and it fails on the default range.

### Passing `evaluation_steps` halves the call count

Omit `evaluation_steps` and `GEval` first asks the model to *write* the steps
(`generate_evaluation_steps`) and then asks it to score
(`generate_evaluation_results`) — two LLM calls per draw. Supplying the steps
skips the first call entirely. At `--repeats 3` over 248 cases that is the
difference between roughly 744 and 1488 judge calls.

### Framing has to alternate, or the column means nothing

The native path alternates prompt framing (`runner._judge` variant 0/1) and
`calibrate.framing_agreement` splits draws on even/odd index (§5). A `GEval`
backend that used one template for every draw would make `frame` report `1.000`
unconditionally — a stability number that measures nothing. So
`deepeval_backend` ships two `GEvalTemplate` subclasses that differ only in block
order: `FramingTemplateResponseFirst` emits `Evaluation Steps:` before
`Test Case:`/`Parameters:`, `FramingTemplateRubricFirst` after. The two render
different strings on identical input, which is what
`test_deepeval_framing_templates_alternate` asserts.

### What the backend deliberately does not do

- **No `async_mode`.** `GEval` defaults to `async_mode=True`, which routes through
  `get_or_create_event_loop()` (`deepeval/utils.py:209`) and applies `nest_asyncio`.
  The repo drives scoring from a plain `for` loop inside a typer command, where
  that can deadlock. The backend passes `async_mode=False`.
- **No JSON contract in the criteria.** The suite rubric is interpolated with
  `contract=""`, because `SCORE_CONTRACT` says "Reply with ONLY a JSON object" and
  contradicts `GEval`'s own template. Leaving the `{contract}` placeholder
  unsubstituted raises `KeyError`.
- **No prompt tuning to force agreement with the native path.** The native path
  bakes the JSON contract into the prompt and the `GEval` path uses its own
  template, so the two are not the same prompt. Disagreement between them is a
  finding to record, not a bug to paper over.

### The measured parity

The two backends were compared on **identical** subject outputs — 16 `factual`
cases from `kenari/qwen3-8-flash`, judged twice per case by
`kenari/deepseek-v4-1-flash` under each backend, so 32 draws per side.

| backend | draws | binarized agreement vs the other |
|---|---:|---:|
| native | 32 | **15 / 16 = 0.938** |
| `deepeval` | 32 | **15 / 16 = 0.938** |

Both backends drew a verdict on every draw — no parse failures on either side —
and they disagree on exactly one case, `fact-002`: the response names Jakarta and
then notes the move to Nusantara. The native judge scores it `1.0` (the reference
appears); the `GEval` judge scores it `0.0` (the response "contradicts" it). That
is a genuine prompt-design difference, not a bug, and it is the kind of case §6
already flags as the hardest for either path.

**A first attempt at this measurement was wrong and is worth recording.** Running
the parity check as two `calibrate` invocations compares different text: `calibrate`
regenerates subject outputs every run and `adapters.chat` pins no temperature
(§7), so 19 of 31 cases came back with different outputs on the second run. That
run reported `0.871` agreement and measured subject drift, not backend parity.
Holding the outputs fixed and varying only the judge is the experiment that
answers the question; the number above is from that version. It is reproducible
with `python scripts/parity_sample.py factual 16`.

### Parse failures stay distinguishable

`judge_case` mirrors `runner._judge`'s `tuple[JudgeVerdict | None, str]`, and the
two `except` arms preserve §3's distinction. `GEval` raises `ValueError` from
`trimAndLoadJson` on unparseable judge output, which is caught first and returned
as `raw != ""` — the model answered outside the contract. Any other exception is
API or infrastructure failure and returns `raw == ""`. So the deepeval path feeds
the same `judge_raw` field and the same "a failing judge does not inherit the
previous verdict" guarantee as the native path, with no change to
`score_with_judge`'s bookkeeping.

---

## Sources

- Norman, Rivera, Hughes. *Reliability without Validity: A Systematic,
  Large-Scale Evaluation of LLM-as-a-Judge Models Across Agreement, Consistency,
  and Bias.* arXiv:2606.19544. — kappa deflation of 33.8–41.3pp across 21 judges;
  consistency–bias paradox; the Minimum Viable Validation Protocol that §5 and §8
  are measured against.
- Panickssery, Bowman, Feng. *LLM Evaluators Recognize and Favor Their Own
  Generations.* arXiv:2404.13076. — self-preference bias and its link to
  self-recognition; the basis for the `self-judge` flag.
- Ho, Huang, Boudin, Aizawa. *LLM-as-a-Judge: Reassessing the Performance of LLMs
  in Extractive QA.* arXiv:2504.11972. — EM correlates 0.17 with human judgment
  versus 0.85 for a judge; direct evidence for the §6 paraphrase finding.
- Haldar, Hockenmaier. *Rating Roulette: Self-Inconsistency in LLM-As-A-Judge
  Frameworks.* Findings of EMNLP 2025. — low intra-rater reliability; disabling
  sampling degrades agreement; majority voting over runs beats both.
- Wongpakaran, Wongpakaran, Wedding, Gwet. *A comparison of Cohen's Kappa and
  Gwet's AC1 when calculating inter-rater reliability coefficients.* BMC Med Res
  Methodol 13:61. — the kappa prevalence paradox and the AC1 alternative.
- Zec et al. *The Paradox of Cohen's Kappa.* Open Nurs J 11:211. — argues AC1
  should be preferred outright; cited as the counterweight to our PABAK choice.
- Wang. *Measuring all the noises of LLM Evals.* arXiv:2512.21326. — prediction
  vs data noise, the `SE = N^(−1/2)·√(p(1−p))` power argument behind `LOW_N`.
- Shi, Ma, Liang, Diao, Ma, Vosoughi. *Judging the Judges: A Systematic Study of
  Position Bias in LLM-as-a-Judge.* arXiv:2406.07791. — position bias is not
  chance and varies by judge and task; the gap in §8.
- Doğruöz, Liao, Blaschke, Prange, Li, Adelani. *Challenges and Recommendations
  for LLM-as-a-Judge in Multilingual Settings and for Low-Resource Languages.*
  arXiv:2607.02235. — only 33 of 650 LLM-as-judge papers in the ACL Anthology
  address multilingual or low-resource settings; validation is skipped precisely
  where it is most needed.
- Li et al. *Grading Scale Impact on LLM-as-a-Judge: Human-LLM Alignment Is
  Highest on 0-5 Grading Scale.* arXiv:2601.03444. — the score scale is a
  protocol parameter, not a convention.
- Arize AI. *How to measure human-LLM judge alignment.* — report raw agreement
  alongside a chance-adjusted metric, plus label counts and the confusion matrix;
  measure judge self-consistency separately from human agreement.

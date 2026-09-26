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

A suite whose cases are all `rubric` has no `expected` value, so there is nothing
in the suite itself to score a judge against. `run_calibration` detects that
(`not any(c.scoreable for c in cases)`) and emits **one row per judge pair**
instead of one row per judge: `build_inter_judge_report(judge, judge_b, ...)`
compares two judges over the same subject outputs. Since §11.1 it first checks
whether the caller passed `labels` and this suite and subject have any: a rubric
suite with labels takes the judge-vs-truth path against them instead, and the
inter-judge path is the fallback for a rubric suite that has none.

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

A rubric suite run with fewer than two judges **and no labels** emits no rows and
prints a warning. That is intended — with one judge there is no comparison, and no
ground truth to fall back on. With labels, one judge is enough: it is scored
against the labels, not against a peer.

The reason is a published and common failure mode. On a near-constant ground
truth, `pe` approaches 1, and kappa collapses toward zero **no matter how well the
judge agrees**. From the shipped study:

| judge | subject | suite | n | po | kappa | pabak | flags |
|---|---|---|---:|---:|---:|---:|---|
| `kenari/deepseek-v4-1-flash` | `kenari/qwen3-8-flash` | factual | 32 | 0.969 | **0.000** | 0.938 | prevalence |
| `kenari/glm-5-3-flash` | `kenari/qwen3-8-flash` | factual_tydiqa | 40 | 0.925 | **−0.034** | 0.850 | prevalence |

Both rows are real output. The first is a judge that agreed with ground truth 31
times out of 32 and is reported as `kappa = 0.000`; the second agreed 37 times out
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
more conservative (on the `factual_tydiqa` cell above, `po = 0.925`,
`pe_AC1 = 0.095`, `AC1 = 0.915` against `pabak = 0.850`; on the 32-case `factual`
cell the two agree closely, `AC1 = 0.968` against `pabak = 0.938`). We report
PABAK and the raw agreement terms rather than a single number, on the principle
that a reader should be able to recompute either coefficient from what we
publish. See §8.

---

## 5. Fragile cells are annotated, not just computed

`_flags` marks seven conditions that make a row hard to read:

| flag | trigger | why |
|---|---|---|
| `low-n` | `n < 30` | one flipped case moves kappa by ~0.1 or more |
| `prevalence` | `pe >= 0.80` | kappa is prevalence-dominated in this cell |
| `self-judge` | `subject == judge` | self-preference bias confounds the row |
| `unstable` | `test_retest < 0.90` | the judge does not agree with itself run to run |
| `framing-sensitive` | `framing_agreement < 0.80` | moving the rubric changes the verdict |
| `canary-fail` | any adversarial case scored `>= 0.5` | the judge passed a case built to catch it |
| `threshold-sensitive` | kappa changes sign across `0.3`/`0.5`/`0.7` | the row's claim depends on the binarization |

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
six such rows, all marked, and five of them are additionally `unstable` and
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
`factual_tydiqa / kenari` posts `kappa = −0.071` — but that row is stable
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

Five of the six `self-judge` rows are simultaneously `unstable` *and*
`framing-sensitive`. The sixth — the local judge on `codemix` — passes its canary,
so it carries `canary-fail` and `threshold-sensitive` instead. Passing is not
confined to that row: the local judge passes 2 of the 3 canaries (`cmx-018` on both
subjects' outputs, `cult-018` on its own) and is caught only on `reg-018`, so its
`cultural` self-judge row carries `canary-fail` as well — see §10. The §8 caveat
that these rows are "confounded by construction" is now quantified rather than
asserted.

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

After the fix the disagreement set on that cell is **6 rows over 6 distinct
cases** (the joiner fix in §11.3 removed the seventh), and the classifier splits it
two ways. Two are the paraphrase case: the judge credited a correct answer the
matcher rejects by construction — `Genin` for *"ninja kelas rendah yang hanya
menjalankan misi kelas D"*, `kecepatan berlari supersonik` for *"berjalan pada
kecepatan supersonik"*. Those stay wrong on purpose: fixing them needs a semantic
matcher or a different ground truth, not a wider regex, and Ho et al. already
quantify the cost of exact match on extractive QA.

The other four are the reverse and are **judge misses, not matcher failures**: the
`expected` string appears verbatim in the output and the matcher scores it `1.0`,
while the judge returns `0.0`. `tydiqa-010` is the clearest — the output reads
*"Lecce terletak di wilayah Puglia (Apulia), bagian selatan **Italia**"* and the
judge's stated reason is that the response "does not explicitly state Italy as the
country". A reference-aware judge given `Italia` in its prompt missed `Italia` in
the response. That is the failure mode §2 exists to prevent, and it is only
visible because the pair rows carry `expected`, `output` and `reason` inline
(§6). It is also why this cell's kappa is *negative* while `pabak = 0.700`: the
matcher is right four more times than the judge is.

**The fix moved agreement up and kappa down, which is not a contradiction.**
On `factual_tydiqa / kenari/qwen3-8-flash / kenari/deepseek-v4-1-flash`, `po` rose
`0.775 → 0.850` across the normalizer fixes, while kappa fell `0.217 → −0.071`.
Correcting the matcher raised the ground-truth pass rate to `0.950`, which raises
chance agreement to `0.860` and deflates kappa past zero — the §4 prevalence
effect, now firing harder because the ground truth is *more* skewed than before.
A kappa of `−0.071` alongside `po = 0.850` is the single least readable row in the
study, and it is entirely an artifact of prevalence. PABAK, which carries no
prevalence term, sits at `0.700` and tracks the raw agreement. This is the
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

**Failures are counted, not dropped.** `n + errors + subject_errors` equals the
suite's case count for every row, so a row can never quietly be computed over a
subset. `errors` counts cases the judge failed on every draw, `subject_errors`
counts cases the subject model failed (which never reached the judge), and both
are published so the sum is checkable from the table. The `err` column is part of
the table for the same reason.

**Repeats are a study parameter, not a default.** `calibrate --repeats N` judges
each case `N` times, alternating prompt framing, and records every draw on the
pair row (`judge_scores`) beside the first successful one (`judge_score`). The
table then carries `retest` and `frame`. The reason not to make it the default is
cost, not principle: `--repeats 3` triples judge calls, and a single-pass run is
still the right tool for a quick diagnostic — it renders both columns `-` rather
than pretending to a stability number it did not measure.

Two consequences worth stating. A case counts as an error only when *every* draw
failed, so `n + errors + subject_errors` still equals the case count and a judge
that fails once in three draws is not silently dropped from the row. And
`test_retest` can be `1.0` on a case that fails under every draw, because only
successful draws enter the statistic — stability of failure is still stability.
Coverage is what `n`, `errors` and `subject_errors` report; stability is a
separate axis.

---

## 8. What we know we get wrong

Recording this is the point of the document — a design note that only lists
strengths is marketing.

1. **The rubric suites had no numeric ground truth.** `cultural`, `register` and
   `codemix` — 96 cases — declare `ground_truth_type: rubric` and carry no
   `expected` value, so there is nothing to score a judge against. They were
   calibrated on a different axis: **inter-judge agreement**, one row per judge
   pair, reported with the same kappa/PABAK/stability columns as the factual rows
   and labelled `vs <judge>` in the `vs` column so a reader cannot mistake them
   for judge-vs-truth. What was wrong was the axis itself — two judges agreeing
   says nothing about whether either is correct, and the multilingual-judge
   literature is unambiguous that reliability is language-conditional
   (Doğruöz et al.; Fu & Liu report mean Fleiss' κ ≈ 0.3 across 25 languages).
   Authoring labels for these 96 cases is the only way to close it, and the labels
   would themselves be a single rater's judgment — the exact reliability problem
   being measured. **§11.1 closes this, and states that the review it added is a
   second model pass rather than the human one the `rater` field was designed for.**

   The inter-judge result is worth recording, because it is what the closed
   version is compared against. Across the 18 rubric pair rows, the two API judges
   agree with each other at a mean `kappa = 0.531` over the four rows where kappa
   is defined (`test_retest = 0.980`, `framing_agreement = 0.964`; the other two
   rows have `pe = 1.0`, where kappa is undefined rather than zero), while any
   pair containing the local judge sits at a mean `kappa = 0.015` (`0.924`,
   `0.798`). Four pairs are `unstable` and six are `framing-sensitive` — every one
   of them a pair with the local judge.

   Six of those 18 pairs are also `prevalence`, which is the honest reading of
   the rubric suites' ceiling. On `codemix / kenari` the two API judges pass 31
   and 30 of 32 cases, so `pe = 0.94` and their `kappa = 0.652` understates an
   agreement of `0.969`; on `cultural / ollama` and `register / ollama` every API
   judge passes 0 of 32, so `pe = 1.0` and kappa is undefined rather than zero.
   Those suites need *harder* cases, not more of them.

2. **Pairwise position bias was unmeasured.** `_judge` presents a single response
   against a rubric, so pairwise position bias does not apply directly. The
   pointwise analogue is now measured: with `--repeats > 1` the rubric alternates
   between after the response (variant 0) and before it (variant 1), and
   `framing_agreement` reports how often the two framings reach the same
   majority verdict. What was still untested is the pairwise form — two responses,
   order swapped — which needs a different judge contract (Shi et al.).
   **§11.2 adds it and measures it.**

3. **Test-retest reliability is measured, but only where `--repeats > 1`.** The
   study's published rows carry `test_retest`, the mean share of draws agreeing
   with their item's majority label. Norman et al.'s central result is that
   consistency and validity are *orthogonal* — a judge can be perfectly
   reproducible and maximally biased — so the two axes are reported side by side
   rather than collapsed. The remaining gap is that `--repeats` is a study
   parameter, not a default: a single-pass run leaves both columns `-`.

4. **The exact-match normalizer still cannot see paraphrase — one row less so
   than before.** The three measured gaps (unit aliases, unit language, superscript
   exponents) are fixed in `_normalize`, and §11.3 closes a fourth: intra-word
   joiners, which split `Al-Qur'an` into `al qur an`. What remains splits two ways.
   Two of the six disagreements on the worst cell are the paraphrase case — a valid
   answer exact match rejects by construction. The other four are the opposite, and
   are the more useful finding: the `expected` string appears verbatim in the
   output, the matcher scores it `1.0`, and the judge returns `0.0`. `_normalize`
   is SQuAD-style plus unit canonicalization; it does not canonicalize scripts, and
   closing the paraphrase gap needs a semantic matcher, not a wider regex. §11.4
   records the affix-aware matcher that was written for it and **reverted**, with
   the measured false-positive count that decided it. Closing the judge-miss gap
   needs nothing from the matcher at all — it is a §2 failure, visible only because
   the pair rows carry `expected`, `output` and `reason` inline.

5. **`prevalence` cells are still published.** `low-n` is gone: the four
   hand-authored suites were grown to 32 cases each, so all 36 rows now carry
   `n >= 32` and no row is flagged for sample size. What replaces it as the
   dominant caveat is `prevalence` — 11 of 36 rows on the regenerated table. That is
   the honest limit of what growing a suite can fix. The `factual` suite is the
   clearest case: the 22 new cases were written to be *harder* — multi-word and
   numeric answers rather than one-word capitals — and they are harder for the
   small local subject (`5/22` passed, against `6/10` on the old cases), but the
   API subject answers all 22 correctly, so the suite pass rate rises
   `0.900 → 0.969` and kappa stays pinned at `0.000` even though `po` improved
   `0.900 → 0.969`. `low-n` was a coverage problem and is fixed; `prevalence` is a
   difficulty problem, and difficulty is a property of the *subject–item* pair, not
   of the item alone.

---

## 9. The GEval backend is opt-in, and what that cost

`src/ideval/metrics/deepeval_backend.py` — `--judge-backend deepeval` routes
judging through deepeval's `GEval` metric instead of the native JSON-contract
prompt. It is **not** the default, and that is a deliberate choice with a price
attached.

The dependency follows the same rule: `deepeval` is an optional extra
(`pip install "id-eval[deepeval]"`), not a core requirement, so a native run
installs only `typer`, `pydantic`, `openai` and `rich`.

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

Both backends returned a verdict on every draw — no parse failures on either side.

The two backends disagree on one case, `fact-002`, where the response names Jakarta
and then notes the planned move to Nusantara: the native judge scored it `1.0` and
the `GEval` judge `0.0`. **That disagreement did not reproduce.** Re-judging the
same case and the same output with both backends returned `1.0` on both, with
reasons that cite the same partial-credit rule — the native judge calling the
extra detail "accurate context [that] does not contradict the answer", the `GEval`
judge calling it "the partial credit condition for correct extra detail". So the
one mismatch is draw-to-draw sampling variance from the unpinned temperature (§7),
not a prompt-design difference, and it is a useful reminder that a single
disagreement in a 16-case sample is inside the noise the study already documents.

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

## 10. Judge quality is measured, not asserted

`src/ideval/calibrate.py` — three claims that §1, §3 and §6 previously supported
only in prose are now fields on `CalibrationReport`, computed by `run_calibration`
from data it already collected. No new judge calls, no new dependency, and no
existing field changed meaning. The published 36-row table was regenerated from
the stored artifact, so all four columns are populated on it rather than deferred
to the next full run: `draws` and `k03` on all 36 rows, `canary` on the 18 rubric
rows (`-` on the 18 `factual*` rows, which carry no canary), and `k07` on 32 (`-`
on the 4 rows where `pe = 1.0` and kappa is undefined at every threshold).

### The canaries were never scored

`canary_outcomes` keys off `reference_note` starting with `ADVERSARIAL` rather
than a hardcoded id list, so §1's canaries are scored by any run that includes
their suites. Scored, they fail. From the instrumentation run:

| suite | case | judge | draws | pass/fail |
|---|---|---|---|---|
| cultural | `cult-018` | `kenari/deepseek-v4-1-flash` | `0.0 / 0.0 / 0.0` | caught |
| cultural | `cult-018` | `ollama/qwen2.5:1.5b` | `1.0 / 0.0` | **passed** |
| register | `reg-018` | `kenari/deepseek-v4-1-flash` | `0.0 / 0.0 / 0.0` | caught |
| register | `reg-018` | `ollama/qwen2.5:1.5b` | `0.0 / 0.3 / 0.25` | caught |
| codemix | `cmx-018` | `kenari/deepseek-v4-1-flash` | `0.2 / 0.2 / 0.1` | caught |
| codemix | `cmx-018` | `ollama/qwen2.5:1.5b` | `0.8 / 1.0 / 0.7` | **passed** |

The `cmx-018` row is the primary finding, and the published artifact corroborates
it independently: there the local judge scores the case `0.7` on
`kenari/qwen3-8-flash`'s output and `0.8` on its own, while both API judges stay
at `0.0`–`0.2`. The case embeds a response that answers a code-mixed
Indonesian–English request in pure formal English — it ignores the Indonesian half
of the prompt entirely — and the local judge rewards it. This is §1's canary
working as designed and finding what it was built to find: the instrument failing
its own check, invisible in every published column because no column carried it.

`cult-018` is the second, and it is a different failure mode. There the local
judge returned `1.0` on one draw and `0.0` on the next: it passes an adversarial
case *intermittently*. A single-pass run would have published whichever draw it
happened to take. `register`'s canary is caught on every draw by both judges, so
the local judge's problem is not "cannot read a canary" but "reads two of three
unreliably". §8 item 1's inter-judge rows are the same judge on the same suites, and
this is the mechanism behind them.

The flag is what makes it visible in a table: `canary-fail` fires on **3** of the
36 rows — the local judge's `cultural` self-judge row and both of its `codemix`
rows (one per subject) — matching the per-case outcomes exactly. The local judge
passes 2 of the 3 canaries (`cmx-018` on both subjects' outputs, `cult-018` on its
own) and is caught on `reg-018` and on the `cultural` row where the subject is
`kenari/qwen3-8-flash`. §11.1's per-row table is the same result read off the
published table.

### Per-draw failure is now a field

`draw_stats` returns `(draws attempted, draws that produced no verdict)`, where
attempted counts `repeats` per case *the subject model answered* — a case the
subject errored on never reached the judge, and counting it would report a subject
failure as a judge failure. On `CalibrationReport` those are `draws` and
`draw_failures`.

The number §3 computed by hand is now read off the artifact. On the published
36-row study the local judge failed `108` of `1464` draws (`7.4%`) while both API
judges failed `0`; on the instrumentation run it failed `21` of `285` (`7.4%`),
and `7` of `96` on the `factual` cell (`7.3%`). Three runs, the same rate to one
decimal. Every one of those rows publishes `err = 0`, because `errors` counts
cases and a case is an error only when *every* draw failed — which is exactly the
conflation §3 warns about, and the reason the field was added rather than the
column reinterpreted.

The `draws` column is also the per-draw cost of `--repeats`, which is the input
to §8 item 3's argument for keeping it a study parameter rather than a default. Making
the cost visible is not a reason to reverse that decision.

### The 0.5 threshold was a convention, and one row turns on it

`build_report` and `build_inter_judge_report` now compute kappa at `0.3`, `0.5`
and `0.7` in a single sweep, reporting the outer two as `kappa_t03`/`kappa_t07`
and the middle as the unchanged `kappa`. `_flags` marks `threshold-sensitive` when
the sweep changes sign — a kappa positive at one threshold and negative at another
is a qualitative change in what the row claims, not a tuned tolerance. `0.0`
counts as neither sign.

In the published 36-row table three rows carry it, all of them the local judge:

|suite|judge|k03|k05|k07|
|---|---|---:|---:|---:|
|`cultural`|`ollama/qwen2.5:1.5b`|0.003|−0.053|0.000|
|`register`|`ollama/qwen2.5:1.5b`|−0.045|0.055|0.071|
|`codemix`|`ollama/qwen2.5:1.5b`|0.116|−0.005|0.000|

Neither API judge carries a `threshold-sensitive` row. The pre-label artifact's
`codemix` pair row (`kenari/deepseek-v4-1-flash` vs `ollama/qwen2.5:1.5b`,
`−0.032 / −0.049 / 0.054`) is the same phenomenon on the inter-judge axis — the
sign of the row is not a property of the suite, and not of either judge alone, but
of where the pass/fail line falls relative to two judges' shared disagreement.
Publishing `−0.049` alone would have implied the pair is worse than chance; the
same observations at `0.7` say the opposite.

The instrumentation run shows the mechanism in a judge-vs-truth cell. On `factual`
the local judge reads `−0.058` at `0.3` and `0.5` but `0.133` at `0.7`, carrying
`threshold-sensitive` alongside `unstable` and `framing-sensitive`. The reason is
visible in the artifact: `fact-007` has ground truth `0.0` and draws
`0.5 / 0.0 / 0.0`, so its first draw decides the label at `0.5` and drops out of
the judge's pass set at `0.7`. One draw, on one case, moves the row's kappa across
zero. That is the boundary §6 flagged as "a real source of instability in the
kappa column" — now a flag on the row instead of a caveat in the prose.

---

## 11. Closing the gaps §8 recorded, and what stays open

`src/ideval/calibrate.py`, `src/ideval/runner.py`, `src/ideval/metrics/base.py` —
§8 lists five things the study knew it got wrong (the fifth, `prevalence`, was
added by `35269b3`). §11.1 and §11.2 close the first two. §11.3 and §11.4 are the
two halves of the fourth: the joiner fix closes the tokenization half and the
affix-aware half was written, measured and reverted, so the paraphrase gap stays
open minus one row. The third (`--repeats` is a study parameter, not a default) and
the fifth (`prevalence` cells are still published) are unchanged by this section
and are stated as open in §8. The numbers below are read from the regenerated
artifacts (`README.md`'s table, `results_pairwise.json` — a local run product, see
§11.2 — and `annotations/rubric_labels.jsonl`), not restated from the design that
produced them.

### 11.1 The rubric suites are now judge-vs-truth, against reviewed labels

`annotations/rubric_labels.jsonl` — 192 rows, one per `(suite, case_id, subject)`,
carrying a `0.0`/`0.5`/`1.0` label and a `rater` field. `calibrate.load_labels`
reads them and `run_calibration` takes `labels=` as its last parameter
(`--annotations` on the CLI). A rubric suite now takes the judge-vs-truth path when
any case carries a label for this subject, so the 18 rubric rows in the README read
`vs = truth` instead of `vs <judge>`. `scripts/label_review.py` is the review loop
that produced the current file: `emit` renders a worksheet, `apply` writes a
reviewer's pass back and is the only writer.

**The unit is the response, not the case.** Two subjects answer the same prompt
differently, so a per-case label would assert identical quality for two different
texts. The three canaries are labelled `0.0` from their own `reference_note`, which
already said "should score LOW".

**The ground truth is read from the label map, never from `r.score`.** This is
load-bearing, not stylistic. `score_with_judge` writes `r.score = scores[0]` for a
non-scoreable case (`runner.py`), so a rubric suite that took the judge-vs-truth
path while its cases stayed non-scoreable would feed each judge its own verdict
back as ground truth and score it as perfect agreement with itself. Verified on the
canary case: a `0.9` verdict in that arrangement contributes `(0.9, 0.9)` and
inflates kappa to `1.000`. Reading gt from the label map makes that impossible — a
case with no label contributes `None` and `pair_scores` drops it, shrinking `n`
rather than inventing agreement.

**Nothing in the suites moved.** `scripts/check_suites.py` fails any scoreable case
in a non-`SCOREABLE` suite, so `ground_truth_type` stays `rubric` and no `expected`
was added. Annotations are
external precisely so `check_suites.py`, the suite files and
`tests/test_core.py`'s rubric-suite test are all untouched. The offline gate still
reads `OK: 6 suites, 248 cases, 3 canaries`, and the 18 `factual*` rows are
byte-identical with and without `--labels`.

The resulting rows, from the regenerated table:

| suite | subject | judge | n | kappa | pabak | canary | flags |
|---|---|---:|---:|---:|---:|---:|---|
| `cultural` | `kenari/qwen3-8-flash` | `kenari/deepseek-v4-1-flash` | 32 | 0.207 | 0.625 | 0/1 | |
| `cultural` | `kenari/qwen3-8-flash` | `kenari/glm-5-3-flash` | 32 | 0.475 | 0.875 | 0/1 | prevalence |
| `cultural` | `kenari/qwen3-8-flash` | `ollama/qwen2.5:1.5b` | 32 | 0.080 | 0.188 | 0/1 | unstable, framing-sensitive |
| `cultural` | `ollama/qwen2.5:1.5b` | `kenari/deepseek-v4-1-flash` | 32 | 0.000 | 0.812 | 0/1 | prevalence |
| `cultural` | `ollama/qwen2.5:1.5b` | `kenari/glm-5-3-flash` | 32 | 0.000 | 0.812 | 0/1 | prevalence |
| `cultural` | `ollama/qwen2.5:1.5b` | `ollama/qwen2.5:1.5b` | 32 | −0.053 | 0.000 | **1/1** | self-judge, unstable, framing-sensitive, canary-fail, threshold-sensitive |
| `register` | `kenari/qwen3-8-flash` | `kenari/deepseek-v4-1-flash` | 32 | 0.207 | 0.625 | 0/1 | |
| `register` | `kenari/qwen3-8-flash` | `kenari/glm-5-3-flash` | 32 | 0.176 | 0.562 | 0/1 | |
| `register` | `kenari/qwen3-8-flash` | `ollama/qwen2.5:1.5b` | 32 | 0.297 | 0.750 | 0/1 | prevalence |
| `register` | `ollama/qwen2.5:1.5b` | `kenari/deepseek-v4-1-flash` | 32 | 0.000 | −0.062 | 0/1 | |
| `register` | `ollama/qwen2.5:1.5b` | `kenari/glm-5-3-flash` | 32 | 0.000 | −0.062 | 0/1 | |
| `register` | `ollama/qwen2.5:1.5b` | `ollama/qwen2.5:1.5b` | 32 | 0.055 | 0.062 | 0/1 | self-judge, unstable, framing-sensitive, threshold-sensitive |
| `codemix` | `kenari/qwen3-8-flash` | `kenari/deepseek-v4-1-flash` | 32 | 1.000 | 1.000 | 0/1 | prevalence |
| `codemix` | `kenari/qwen3-8-flash` | `kenari/glm-5-3-flash` | 32 | 0.652 | 0.938 | 0/1 | prevalence |
| `codemix` | `kenari/qwen3-8-flash` | `ollama/qwen2.5:1.5b` | 32 | −0.049 | 0.750 | **1/1** | prevalence, canary-fail |
| `codemix` | `ollama/qwen2.5:1.5b` | `kenari/deepseek-v4-1-flash` | 32 | 0.033 | −0.250 | 0/1 | |
| `codemix` | `ollama/qwen2.5:1.5b` | `kenari/glm-5-3-flash` | 32 | 0.067 | −0.188 | 0/1 | |
| `codemix` | `ollama/qwen2.5:1.5b` | `ollama/qwen2.5:1.5b` | 32 | −0.005 | 0.250 | **1/1** | self-judge, canary-fail, threshold-sensitive |

**What this replaced, and what it cost.** The old rubric rows answered "do two
judges agree with each other". These answer "does a judge agree with one rater",
which is the question §8 item 1 said was the only way to close the gap. The mean kappa
is `0.235` across the 12 API-judge rows and `0.054` across the 6 local-judge rows —
lower than the inter-judge `0.531` the two API judges posted against each other,
which is the expected direction: agreement between two judges drawn from the same
model family overstates agreement with a third party's judgment.

**The labels are reviewed, and still the single point of failure.** Every row now
carries `rater: review:assistant` — but that is a *second model pass*, not a human
one. `scripts/label_review.py emit` renders the whole worksheet (prompt, rubric
note, draft label with its rationale, the stored response); the pass re-read all
192 rows against their suites' rubrics and changed 4 labels: `cult-006 / kenari`
`1.0 -> 0.5` (it names family and guests as the feeders rather than the couple
feeding each other, and invents a mantra), `cult-007 / kenari` `0.5 -> 1.0` (the
draft's stated reason — thin on cross-faith scheduling — does not hold, since the
response does cover a non-halal option and not assuming every participant fasts),
`cmx-007 / kenari` `1.0 -> 0.5` (correct behavior, but it answers an Indonesian
prompt in pure English, the same language half the draft scores `cmx-003` at 0.5
for), and `cmx-008 / ollama` `0.5 -> 0.0` (pure English on PayPal/Venmo with
invented UI, the rubric's pure-English fail clause — the reading the draft already
applies to `cmx-027`). The other 188 rows were confirmed at their draft label and
keep the draft's rationale.

That review is a real second reading, and it caught a genuinely over-credited row
and a genuinely under-credited one. It is not the independent human pass the
`rater` field was designed to hook, so the labels are still the single point of
failure: a second model reading the same drafts shares the first pass's blind
spots in a way an independent human would not, and nothing here establishes the
labels as ground truth in the sense the `factual` suites' `expected` values are.
The label distribution is skewed in a way that matters: `codemix` labels pass
`0.812` of the time, so its two API rows carry `prevalence` and their kappa is the
least readable number in the block. `rater: review:<name>` for a human reviewer
remains the open hook.

### 11.2 Pairwise position bias is measured, and two of three judges show none

`src/ideval/runner.py` — `_judge_pair` presents two responses under a fixed rubric
and swaps which is `A`; `metrics/base.PairVerdict` + `parse_pair_verdict` are the
pairwise contract (same tolerant shape as `parse_verdict`, keyed on `winner`, and
rejecting anything that is not exactly `A` or `B`); `calibrate.pairwise_flip_rate`
is the statistic. `scripts/pairwise_probe.py` builds pairs from the stored
artifact: for a `factual` case, the API judge passed one subject's output and
failed the other's, so the pair has a known better response — a sanity anchor, not
the measurement.

`order` and `framing` are **separate arguments** to `_judge_pair`. Folding them into
one would swap the responses when the caller meant to move the rubric, which
destroys the comparison the probe exists to make; the probe holds `order` fixed and
alternates `framing` across its `--repeats`. Each draw's verdict is resolved from
its letter back to the *response* it named, so the two orders are compared on
content identity — a position-invariant judge returns the same response both times,
not the same letter.

Result, `--suite factual --repeats 2`, 21 pairs, from `results_pairwise.json`:

| judge | pairs judged in both orders | flip rate | picked the known-better response | unparsed draws |
|---|---:|---:|---:|---:|
| `kenari/deepseek-v4-1-flash` | 20 | **0.000** | 1.000 | 0 |
| `kenari/glm-5-3-flash` | 21 | **0.000** | 1.000 | 0 |
| `ollama/qwen2.5:1.5b` | 7 | **0.571** | 0.571 | 7 |

Both API judges picked the known-better response on every pair and never changed
their answer when the responses were swapped. That is a `0.0` flip rate, and it is
a **valid result, not a null one**: it says the pairwise form of position bias does
not fire on this judge, this suite and this pair construction, which is the
question §8 item 2 left open. One `deepseek` pair (`fact-007`) is excluded because its
two forward draws split `A`/`B` and no majority exists — the same `fact-007` that
§10 shows carrying a `0.5` first draw, so the exclusion is the boundary case
already documented rather than a new anomaly.

The local judge is the outlier again, and worse here than on the pointwise axis.
It flipped on 4 of the 7 pairs it could answer at all (`0.571`), 14 pairs had no
majority under either order, and 7 individual draws did not parse. So the
`framing-sensitive` flag on its rows understates the problem: on the pairwise
protocol it is both unreliable *and* order-dependent, and its `0.571` better-share
means it is close to a coin flip on which of two responses is better even when one
was selected by a competent judge.

**This is a separate protocol, not a README column.** A flip rate needs two
responses per item; the 36-row table has one response per case per subject, so
there is no column of it that would mean anything. It is reported here and in
`docs/calibration-study.md` instead.

**`results_pairwise.json` is a local run product, not a shipped artifact.** It is
gitignored (`results*.json`) and is not attached to the release, which carries
`results_calibration.json` alone, so the table above is a measurement rather than
something a reader can recompute offline. Re-running it needs two live judges and
`scripts/pairwise_probe.py`; the numbers it would ship are already in this section
and in `docs/calibration-study.md`.

### 11.3 The `tydiqa-019` disagreement was a normalizer gap, not paraphrase

`src/ideval/runner.py` — `_PUNCT` replaces every non-word character with a space,
so an intra-word apostrophe or hyphen split one token into two:

```
before (_JOINER): _normalize("Al-Qur'an")  ->  "al qur an"
                  _normalize("Alquran")    ->  "alquran"
after  (_JOINER): _normalize("Al-Qur'an")  ->  "alquran"
```

`tydiqa-019`'s expected value is `salinan pertama Alquran`, and one subject wrote
`Al-Qur'an`. The matcher scored `0.0` on a correct answer, and §6 had classified
that row as the paraphrase case — a semantic-matcher problem. It was not: it was a
tokenization bug, and `_JOINER` (`(?<=\w)['\u2019\-](?=\w)`, applied before
`_PUNCT`) closes it by deleting joiners between word characters.

Measured blast radius on all 888 scoreable pair rows:

| | rows | cases | direction |
|---|---:|---|---|
| pair rows whose recomputed `gt` differs from the stored `gt` | 3 | `tydiqa-019` only | `0.0 → 1.0` |
| of those, genuine matches | 3 | `tydiqa-019` | the output contains the expected answer |
| false positives (a `0.0` row moved to `1.0`) | **0** | — | — |

Three rows, one case, all in the correct direction, nothing else in the corpus
moved, and the eight pinned `_match_exact`/`_normalize` tests in
`tests/test_core.py` all hold at their existing values. That last point is the
guard: `_JOINER` must not make `test_normalize_still_rejects_genuine_misses` start
matching.

### 11.4 The affix-aware containment half was written, measured, and reverted

The plan for the same step also replaced `_match_exact`'s substring test with
affix-aware token containment, so `berlari` would match `berjalan`-class
morphology: strip the Indonesian affix set (`meN-`/`men-`/`mem-`/`ber-`/`ter-`/
`di-`/`pe-`, `-kan`/`-nya`/`-an`/`-i`) from both sides and require every stripped
expected token to be present in the stripped output set.

It was implemented, audited, and **reverted**. The audit is what decided it. The
rows below are the affix half's *additions* on top of the joiner fix — the joiner's
own three `tydiqa-019` rows are excluded:

| affix half's added flips | rows | cases | verdict |
|---|---:|---|---|
| pair rows moved to `1.0` from a stored `0.0` | 9 | `tydiqa-015`, `tydiqa-022`, `tydiqa-025` | — |
| of those, **false positives** | 6 | `tydiqa-015`, `tydiqa-022` | wrong answer scored `1.0` |
| of those, defensible | 3 | `tydiqa-025` | right answer, broken tokenization |

The false positives are the disqualifying part. `tydiqa-015`'s expected value is
`keriting merah`; the response offers *green* curly chilis (`Cabe Keriting Hijau`)
and mentions `merah` elsewhere in the paragraph, so bag-of-words containment
passes while the answer is wrong. `tydiqa-022`'s expected value is `agama Jawa`;
the response says `bahasa Jawa`. Both flipped to `1.0`. The plan's criterion was
explicit — any non-zero false-positive count reverts the half — so the affix
matcher is not in the code.

Two mechanisms made it fail, and both are worth recording because the idea is
attractive enough to be re-proposed:

- **Bag-of-words containment discards word order and adjacency.** Substring
  containment at least required the expected phrase to appear contiguously; a token
  set does not, so `agama` + `Jawa` anywhere in a long response is enough.
- **The strip is not a stemmer.** The `_MIN_STEM` guard prevented the shortest
  stems but not the wrong ones: `merah → rah`, `pertama → rtama`, `berjalan → jal`.
  `tydiqa-025`'s flip is only "defensible" because `jal` happened to also appear,
  which is luck rather than morphology.

**§8 item 4 therefore stays open, minus one row.** The paraphrase gap is real: on the
worst cell, 2 of the 6 remaining disagreements are the matcher rejecting a correct
answer (`Genin` for *"ninja kelas rendah…"*, `kecepatan berlari supersonik` for
*"berjalan pada kecepatan supersonik"*). Closing it needs a semantic matcher or a
different ground truth, not a wider regex or a token set — which is what the
reverted experiment demonstrates rather than asserts. The joiner fix is kept
because it is a different kind of change: it repairs tokenization without loosening
what counts as a match.

### 11.5 The README table was regenerated offline

`README.md`'s table was rebuilt from `results_calibration.json` by
`scripts/replay_calibration.py`, not by a new `calibrate` run, and the 10 value
columns that predate the round-1 additions (`n`, `kappa`, `pabak`, `retest`,
`frame`, `precision`, `recall`, `spearman`, `err`, `flags`) reproduce row for row.
The table carries 15 value columns now: `8e0088f` added `canary`, `draws`, `k03`
and `k07`, and `bcc9f10` added `subj_err`. `adapters.chat` pins no
temperature (§7), so a fresh run would judge different text and every number would
move for reasons unrelated to this change; a replay is the only way to change what
the table *means* while holding what it *measures* fixed. The judge verdicts in the
table are the M2 study's — only the ground truth for the 18 rubric rows is new.
The replay asserts that recomputing `gt` from each row's stored `output` and
`expected` reproduces the stored `gt`, and exits non-zero otherwise; `--match-audit`
switches that assertion to a report, which is how the two blast-radius tables above
were measured.

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

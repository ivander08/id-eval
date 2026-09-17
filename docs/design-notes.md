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

The reason is a published and common failure mode. On a near-constant ground
truth, `pe` approaches 1, and kappa collapses toward zero **no matter how well the
judge agrees**. From the shipped study:

| judge | subject | suite | n | po | kappa | pabak | flags |
|---|---|---|---:|---:|---:|---:|---|
| `kenari/deepseek-v4-1-flash` | `kenari/qwen3-8-flash` | factual | 10 | 0.900 | **0.000** | 0.800 | low-n, prevalence |
| `kenari/glm-5-3-flash` | `ollama/qwen2.5:1.5b` | factual | 10 | 0.900 | **0.800** | 0.800 | low-n |

Both rows are real output. The first is a judge that agreed with ground truth 9
times out of 10 and is reported as `kappa = 0.000`. A reader given only the kappa
column would conclude the judge is worthless. It is not — the ground truth is
skewed and kappa is the wrong instrument for that cell. `pabak = 2·po − 1` carries
no prevalence term and stays readable there.

`agreement_terms` is the shared implementation; `cohens_kappa` delegates to it
rather than duplicating the formula, so the three existing kappa tests
(`test_kappa_known_value`, `test_kappa_perfect_agreement`,
`test_kappa_mismatched_lengths`) guard both statistics at once.

`test_pabak_exposes_what_kappa_hides` pins the exact degenerate cell above:
`kappa == 0.0` and `pabak == 0.8` on the same ten observations.

### Limits of this choice

PABAK removes prevalence **and** bias, so it reads optimistically — it is not a
strictly better kappa. The literature's other candidate is Gwet's AC1, which is
more conservative (on the degenerate cell above, `po = 0.900`, `pe_AC1 = 0.095`,
`AC1 = 0.890`). We report PABAK and the raw agreement terms rather than a single
number, on the principle that a reader should be able to recompute either
coefficient from what we publish. See §8.

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
to `n = 80` is not reporting uncertainty.

The `self-judge` flag is the most important flag in the table. Panickssery et al. show
that LLM evaluators recognise and favour their own generations, with the strength
of the bias tracking self-recognition capability — so a row where subject and
judge are the same model is confounded by construction. The shipped study has
three such rows, all marked, and all three are additionally `unstable` and
`framing-sensitive` — the local judge is both the most biased and the least
self-consistent row in the table.

`unstable` and `framing-sensitive` are the two flags that only exist when
`--repeats > 1`. They are the operational form of Norman et al.'s consistency–
validity orthogonality: a row can agree with ground truth perfectly and still be
flagged `unstable`, and that combination is the one worth reading first.

### What the repeats measured

Three draws per case, rubric position alternating, across 258 cases per judge:

| judge | `test_retest` | `framing_agreement` | draws disagreeing | per-draw parse failure |
|---|---:|---:|---:|---:|
| `kenari/glm-5-3-flash` | 0.994 | 0.983 | 6.6% | 0.0% |
| `kenari/deepseek-v4-1-flash` | 0.980 | 0.941 | 9.7% | 0.0% |
| `ollama/qwen2.5:1.5b` | 0.787 | 0.473 | 71.6% | 7.4% |

Three things follow, none of which the single-pass table could show.

**Stability separates the judges, and it separates them the right way.** The local
judge sits `0.19` below both API judges on `test_retest` — far outside the `0.02`
that would indicate the draws were not independent. That is the falsification
test for the statistic itself: if a stability number cannot pick out the judge
that fails 7.4% of draws and flips its verdict on 72% of cases, it is measuring
nothing. Note that neither API judge failed a single draw, so the `err` column
alone would have hidden this entirely.

**Agreement and stability are orthogonal here, exactly as Norman et al. claim.**
`kenari/glm-5-3-flash` on `factual_indommlu / ollama` posts `kappa = 0.915` *and*
`test_retest = 1.000` with zero flags. `kenari/deepseek-v4-1-flash` on
`factual_tydiqa / kenari` posts a nearly identical `kappa = 0.155` — but that row
is stable (`0.991`), while the local judge's `factual / kenari` row has a
comparable `kappa = 0.138` and is *not* (`0.800`, `unstable`). Two rows a reader
would previously have ranked identically are now distinguishable.

**Framing sensitivity is the sharper instrument, and it catches the boundary
cases.** The local judge's framing agreement (`0.473`) is worse than its
test-retest (`0.787`) by a wide margin: it is not just noisy run to run, it
*systematically* answers differently depending on whether the rubric precedes or
follows the response. The API judges lose far less (`0.983`, `0.941`). That is the
pointwise analogue of position bias showing up as a measurable, judge-specific
effect rather than a suspicion — see §8.

All three local-judge rows are simultaneously `self-judge`, `unstable`, and
`framing-sensitive`. The §8 caveat that these rows are "confounded by
construction" is now quantified rather than asserted.

---

## 6. The artifact is auditable without a join

`run_calibration` writes one row per (suite, subject, judge, case) carrying
`expected`, `output` and the judge's `reason` inline:

```python
{"suite", "subject", "judge", "case_id", "gt", "judge_score", "judge_scores",
 "expected", "output", "reason"}
```

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
kappa is unchanged to three decimals. On the re-run artifact the same comparison
is 18 of 237 rows — the same three case ids, now crossed with three judges and
two subjects — and still zero movement outside `factual_tydiqa`.

The three regexes are the minimum set that closes the measured gaps; adding more
units would widen the false-match surface for no corpus benefit.
`test_normalize_still_rejects_genuine_misses` is the guard on that widening.

After the fix the disagreement set on that cell collapses to **6 rows over 6
distinct cases, every one of them a valid paraphrase** the judge credited
correctly — `Genin` for *"ninja kelas rendah yang hanya menjalankan misi kelas D"*,
`kecepatan berlari supersonik` for *"berjalan pada kecepatan supersonik"*, and so
on. Those stay wrong on purpose: fixing them needs a semantic matcher or a
different ground truth, not a wider regex, and Ho et al. already quantify the
cost of exact match on extractive QA.

**The fix moved agreement up and kappa down, which is not a contradiction.**
On `factual_tydiqa / kenari/qwen3-8-flash / kenari/deepseek-v4-1-flash`, `po`
rises `0.775 → 0.821` while kappa falls `0.217 → 0.155`. Correcting the matcher
raised the ground-truth pass rate to `0.821`, which raises chance agreement to
`0.788` and deflates kappa — the §4 prevalence effect, now firing harder because
the ground truth is *more* skewed than before. PABAK, which carries no prevalence
term, rises `0.550 → 0.641` and tracks the raw agreement. This is the clearest
instance in the study of why kappa alone is not an agreement report.

**One consequence worth flagging:** a half-point verdict sits exactly on the
binarization threshold, where it decides the pass/fail label. In the re-run
artifact 42 of 774 pair rows carry at least one draw at exactly `0.5`, and 16 rows
publish `judge_score == 0.5`. That is a real source of instability in the kappa
column. It is no longer unmeasured — `test_retest` counts a draw as a pass at
`>= 0.5`, so a judge that lands on the boundary run to run shows up as
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

1. **The rubric suites are uncalibrated.** `factual`, `factual_indommlu` and
   `factual_tydiqa` all have matcher-decidable ground truth and are the only
   suites the calibration study covers. `cultural`, `register` and `codemix` — 54
   cases — are scored by judges whose agreement has never been measured. Their
   numbers should be read as unvalidated. The multilingual-judge literature is
   unambiguous that reliability is language-conditional and should not be assumed
   (Doğruöz et al.; Fu & Liu report mean Fleiss' κ ≈ 0.3 across 25 languages).

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
   `_normalize`. What remains is the dominant cause: with those gaps closed, the
   disagreement set on the worst cell is **6 rows over 6 distinct cases, every one
   a valid paraphrase** that exact match rejects by construction. `_normalize` is
   SQuAD-style plus unit canonicalization; it does not canonicalize scripts or
   Indonesian affixes, and closing the paraphrase gap needs a semantic matcher,
   not a wider regex.

5. **`low-n` cells are published anyway.** Flagging a 10-case cell is not the same
   as fixing it. The correct fix is more cases, which is the M1 line item.

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

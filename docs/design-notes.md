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

`EvalResult` carries three separate judge fields:

```python
judge_score: float | None = None   # the parsed verdict
judge_reason: str | None = None    # the judge's stated rationale
judge_raw: str | None = None       # raw judge text, set ONLY when parsing failed
```

`runner._judge` returns `tuple[JudgeVerdict | None, str]`, so the raw text survives
a parse failure instead of being discarded. The two failure modes stay
distinguishable and are documented in the docstring:

- `raw == ""` → the API call raised. An infrastructure problem.
- `raw != ""` with a `None` verdict → the model answered, but not in the contract
  format. A model problem.

Collapsing those two into a single `errors` counter, as most harnesses do, throws
away the only evidence that tells you which one you have. A ~8% judge failure rate
is either a retry policy question or a prompt-contract question, and you cannot
tell which without the raw text.

The rationale is also captured per row, because a judge's stated reason is the
audit trail for its score. `score_with_judge` resets `judge_reason` and
`judge_raw` before every judge pass, for the same reason it resets `judge_score`:
otherwise a failing judge silently inherits the previous judge's rationale. There
is a regression test for that inheritance specifically.

---

## 4. Cohen's kappa alone is not an agreement report

`src/ideval/calibrate.py` computes `po` (observed agreement), `pe` (chance
agreement), `kappa`, and `pabak` — and reports all four.

The reason is a published and common failure mode. On a near-constant ground
truth, `pe` approaches 1, and kappa collapses toward zero **no matter how well the
judge agrees**. From the shipped study:

| judge | subject | suite | n | po | kappa | pabak | flags |
|---|---|---|---:|---:|---:|---:|---|
| `kenari/deepseek-v4-1-flash` | `kenari/qwen3-8-flash` | factual | 10 | 0.900 | **0.000** | 0.800 | low-n, prevalence |
| `kenari/glm-5-3-flash` | `ollama/qwen2.5:1.5b` | factual | 10 | 1.000 | **1.000** | 1.000 | low-n |

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

`_flags` marks three conditions that make a row hard to read:

| flag | trigger | why |
|---|---|---|
| `low-n` | `n < 30` | one flipped case moves kappa by ~0.1 or more |
| `prevalence` | `pe >= 0.80` | kappa is prevalence-dominated in this cell |
| `self-judge` | `subject == judge` | self-preference bias confounds the row |

The `low-n` threshold is a power argument, not a convention. For a proportion,
`SE = N^(−1/2)·√(p(1−p))`; at `n = 10, p = 0.6` that is `±0.30` at 95%, and a
single flipped case swings kappa by `0.20`. At `n = 300` the same flip moves it by
`0.007`. A table that prints `n = 10` and `kappa = 1.000` with equal visual weight
to `n = 80` is not reporting uncertainty.

The `self-judge` flag is the most important of the three. Panickssery et al. show
that LLM evaluators recognise and favour their own generations, with the strength
of the bias tracking self-recognition capability — so a row where subject and
judge are the same model is confounded by construction. The shipped study has
three such rows, all marked, all with `err > 0` (the local judge also fails more
often on the hardest suite).

---

## 6. The artifact is auditable without a join

`run_calibration` writes one row per (suite, subject, judge, case) carrying
`expected`, `output` and the judge's `reason` inline:

```python
{"suite", "subject", "judge", "case_id", "gt", "judge_score",
 "expected", "output", "reason"}
```

This is a deliberate denormalisation. `results_calibration.json` is a gitignored
diagnostic artifact, not a published dataset, so the cost of repeating each
subject output once per judge is irrelevant — and the benefit is that **any
disagreement in the table can be read directly out of the file** without
regenerating outputs or joining against a side table.

That property is what turned the largest disagreement in the study from an
unexplained number into a finding. Filtering
`gt == 0.0 and judge_score >= 0.5` on `factual_tydiqa / kenari/qwen3-8-flash`
yields 22 rows over 9 distinct cases, and the inline `expected` / `output` /
`reason` triples classify every one of them:

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

**One consequence worth flagging:** one row scored `0.5`, which is exactly the
binarization threshold. 20 of 756 pair rows sit on that boundary, where a
half-point decides the pass/fail label. That is a real source of instability in
the kappa column and is not currently flagged.

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

2. **Position bias is unmeasured.** `_judge` presents a single response against a
   rubric, so pairwise position bias does not apply directly — but the
   pointwise analogue (does the score change when the reference and response
   swap order, or when rubric framing changes?) is untested. Position bias is
   among the best-documented LLM-judge failure modes (Shi et al.).

3. **Test-retest reliability is unmeasured.** Every cell is a single run. Norman
   et al.'s central result is that consistency and validity are *orthogonal* — a
   judge can be perfectly reproducible and maximally biased — so reporting
   agreement without a replicate count leaves the most important axis blank.

4. **The exact-match normalizer has known gaps.** §6 found three concrete ones
   (unit aliases, unit language, superscript exponents). They are unfixed.
   `_normalize` is SQuAD-style: lowercase, strip punctuation, collapse whitespace.
   It does not canonicalize units, scripts, or Indonesian affixes.

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

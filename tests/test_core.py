from pathlib import Path

import pytest

from ideval.calibrate import (agreement_terms, build_inter_judge_report, build_report,
                              canary_outcomes, cohens_kappa, draw_stats, framing_agreement,
                              pabak, pair_scores, precision_recall, spearman)
from ideval.calibrate import test_retest as retest_agreement  # aliased: pytest collects bare `test_*` names
from ideval.metrics.base import parse_verdict
from ideval.reporting import update_readme_table
from ideval.runner import _match_choice, _match_exact, _normalize
from ideval.schema import EvalResult, TestCase as CaseModel
from ideval.schema import load_suite, suite_summaries


def test_parse_verdict_plain_json():
    v = parse_verdict('{"score": 0.8, "reason": "ok"}')
    assert v is not None and v.score == 0.8


def test_parse_verdict_surrounded_by_prose():
    v = parse_verdict('Sure! Here is my evaluation:\n{"score": 0.25, "reason": "register salah"}\nHope that helps!')
    assert v is not None and v.score == 0.25


def test_parse_verdict_score_clamped():
    v = parse_verdict('{"score": 7, "reason": ""}')
    assert v is not None and v.score == 1.0


def test_parse_verdict_rejects_non_numeric():
    assert parse_verdict('{"score": "high", "reason": ""}') is None
    assert parse_verdict("no json here") is None


def test_kappa_perfect_agreement():
    a = [1.0, 0.0, 1.0, 0.0]
    assert cohens_kappa(a, a) == 1.0


def test_kappa_known_value():
    # textbook example: po=0.75, pe=0.5 -> kappa=0.5
    a = [1, 1, 0, 0, 1, 0, 1, 0]
    b = [1, 0, 0, 0, 1, 1, 1, 0]
    assert abs(cohens_kappa([float(x) for x in a], [float(x) for x in b]) - 0.5) < 1e-9


def test_kappa_mismatched_lengths():
    assert cohens_kappa([1.0], [1.0, 0.0]) is None


def test_precision_recall_perfect():
    a = [1.0, 0.0, 1.0, 0.0]
    p, r = precision_recall(a, a)
    assert p == 1.0 and r == 1.0


def test_precision_recall_asymmetric():
    # judge passes everything: recall=1, precision=2/3 (1 false positive)
    judge = [1.0, 1.0, 1.0]
    truth = [1.0, 0.0, 1.0]
    p, r = precision_recall(judge, truth)
    assert abs(p - 2 / 3) < 1e-9 and r == 1.0


def test_precision_recall_no_positives():
    p, r = precision_recall([0.0, 0.0], [0.0, 0.0])
    assert p is None and r is None


def test_spearman_perfect_monotonic():
    assert abs(spearman([1, 2, 3], [10, 20, 30]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3], [30, 20, 10]) - (-1.0)) < 1e-9


def test_spearman_with_ties():
    # tie-handled Pearson-on-ranks: sqrt(3)/2, not the tie-free shortcut 0.5
    assert abs(spearman([1, 1, 2], [10, 20, 30]) - 0.8660254037844387) < 1e-9


def test_match_exact_embedded_in_sentence():
    assert _match_exact("Ibu kota Provinsi Jawa Barat adalah Bandung.", "Bandung") == 1.0


def test_match_exact_trailing_punctuation():
    assert _match_exact("Rupiah.", "Rupiah") == 1.0


def test_match_exact_case_insensitive():
    assert _match_exact("JAKARTA adalah ibu kota", "jakarta") == 1.0


def test_match_exact_genuine_miss_stays_zero():
    assert _match_exact("Mount Everest", "Puncak Jaya") == 0.0


def test_match_exact_empty_expected_is_zero():
    assert _match_exact("anything", "") == 0.0


def test_normalize_canonicalizes_superscript():
    assert _match_exact("Luasnya 637.657 km²", "637.657 km2") == 1.0


def test_normalize_canonicalizes_units():
    assert _match_exact("sekitar 25 hektare", "25 ha") == 1.0
    assert _match_exact("20.779 kilometer persegi", "20,779 square kilometres") == 1.0


def test_normalize_still_rejects_genuine_misses():
    assert _match_exact("Mount Everest", "Puncak Jaya") == 0.0
    assert _match_exact("1892", "1889") == 0.0
    assert _match_exact("Dollar", "Rupiah") == 0.0


def test_match_choice_last_letter_wins():
    assert _match_choice("Jawabannya C.", "C") == 1.0
    assert _match_choice("A. salah\nJawaban: B", "B") == 1.0


def test_match_choice_rejects_wrong_letter():
    assert _match_choice("Jawabannya D", "C") == 0.0


def test_match_choice_is_case_sensitive():
    # lowercase standalone 'a' in Indonesian text is a word, not an MC answer
    assert _match_choice("Kalimat a ini tentang Benda", "A") == 0.0
    assert _match_choice("jawabannya c.", "C") == 0.0
    assert _match_choice("Jawabannya C.", "C") == 1.0


def test_match_choice_letters_in_context_lines():
    # options listing then explicit answer: last standalone letter is the answer
    assert _match_choice("A. Galungan\nB. Kuningan\nJawab: D. Waisak", "D") == 1.0


def test_suite_summaries():
    suites = {s.name: s for s in suite_summaries()}
    assert {"factual", "cultural", "register", "codemix"} <= set(suites)
    assert suites["factual"].scoreable == suites["factual"].count


def test_load_suite_and_scoreable():
    cases = load_suite("factual")
    assert cases and all(c.suite == "factual" for c in cases)
    assert cases[0].scoreable


def test_case_model_rejects_bad_ground_truth_type():
    with pytest.raises(Exception):
        CaseModel(id="x", suite="s", input="i", ground_truth_type="magic")


def test_pair_scores_drops_unpaired_and_keeps_order():
    judge, gt = pair_scores([1.0, None, 0.0], [1.0, 1.0, None])
    assert judge == [1.0] and gt == [1.0]
    judge, gt = pair_scores([0.0, 1.0], [0.0, 1.0])
    assert judge == [0.0, 1.0] and gt == [0.0, 1.0]


def test_build_report_known_kappa_and_missing_judge_score():
    # po=0.75, pe=0.5 -> kappa=0.5 (same textbook value pinned above)
    report = build_report("j", "factual", [1.0, 1.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0], errors=1)
    assert report.n == 4
    assert abs(report.kappa - 0.5) < 1e-9
    assert report.errors == 1

    # an unscored case shrinks n instead of shifting the statistics
    report = build_report("j", "factual", [1.0, 1.0, 0.0, 0.0, None], [1.0, 0.0, 0.0, 0.0, 1.0])
    assert report.n == 4
    assert abs(report.kappa - 0.5) < 1e-9


def test_pabak_endpoints():
    assert pabak([1.0, 0.0, 1.0, 0.0], [1.0, 0.0, 1.0, 0.0]) == 1.0
    assert pabak([1.0, 0.0], [0.0, 1.0]) == -1.0
    assert pabak([1.0], [1.0, 0.0]) is None


def test_pabak_exposes_what_kappa_hides():
    # the published degenerate cell: 10 ground-truth passes, 9 judge passes
    gt, judge = [1.0] * 10, [1.0] * 9 + [0.0]
    assert cohens_kappa(judge, gt) == 0.0
    assert pabak(judge, gt) == 0.8


def test_agreement_terms_reports_chance_agreement():
    po, pe = agreement_terms([1.0] * 10, [1.0] * 9 + [0.0])
    assert po == 0.9 and pe == 0.9


def test_build_report_flags():
    report = build_report("m", "factual", [1.0, 0.0, 1.0, 0.0], [1.0, 0.0, 1.0, 0.0], subject="m")
    assert report.flags == ["low-n", "self-judge"]

    report = build_report("j", "factual", [1.0] * 40, [1.0] * 40, subject="m")
    assert "low-n" not in report.flags
    assert "prevalence" in report.flags


def test_test_retest_perfect_and_mixed():
    assert retest_agreement([[1.0, 1.0, 1.0], [0.0, 0.0, 0.0]]) == 1.0
    assert retest_agreement([[1.0, 1.0, 0.0]]) == 2 / 3
    assert retest_agreement([[1.0]]) is None


def test_framing_agreement_detects_swap():
    assert framing_agreement([[1.0, 1.0, 1.0, 1.0]]) == 1.0
    assert framing_agreement([[1.0, 0.0, 1.0, 0.0]]) == 0.0
    assert framing_agreement([[1.0]]) is None


def test_build_report_flags_unstable_and_framing():
    report = build_report("j", "factual", [1.0] * 40, [1.0] * 40, subject="m",
                          draws=[[1.0, 0.0]] * 40)
    assert "unstable" in report.flags and "framing-sensitive" in report.flags


def test_canary_outcomes_flags_a_passing_judge():
    # the canary's failure mode is the judge scoring it AT or above threshold
    canary = CaseModel(id="canary-case", suite="s", input="i", ground_truth_type="rubric",
                       reference_note="ADVERSARIAL: should score LOW")
    plain = CaseModel(id="plain-case", suite="s", input="i", ground_truth_type="rubric")
    passing = EvalResult(case_id="canary-case", suite="s", model="m", output="o", score=0.8)
    missing = EvalResult(case_id="plain-case", suite="s", model="m", output="o", score=0.2)
    assert canary_outcomes([canary, plain], [passing, missing]) == {"canary-case": True}

    caught = EvalResult(case_id="canary-case", suite="s", model="m", output="o", score=0.2)
    assert canary_outcomes([canary, plain], [caught, missing]) == {"canary-case": False}


def test_draw_stats_excludes_subject_failures():
    # a case the subject model failed never reached the judge, so its draws are
    # not attempted at all -- counting them would report a subject failure as one
    subject_failed = EvalResult(case_id="a", suite="s", model="m", output="", error="boom")
    complete = EvalResult(case_id="b", suite="s", model="m", output="o",
                          judge_repeats=[1.0, 1.0, 1.0])
    partial = EvalResult(case_id="c", suite="s", model="m", output="o", judge_repeats=[1.0])
    assert draw_stats([subject_failed, complete, partial], 3) == (6, 2)


def test_build_report_reports_kappa_across_thresholds():
    # the 0.5 draw sits exactly on the boundary: it passes at 0.3 and 0.5, fails
    # at 0.7, so the judge's binarized pass set shrinks as the threshold rises
    judge_scores = [0.9, 0.9, 0.1, 0.5]
    gt_scores = [1.0, 1.0, 1.0, 0.0]
    report = build_report("j", "factual", judge_scores, gt_scores, subject="m")
    assert report.kappa_t03 < 0 < report.kappa_t07
    assert "threshold-sensitive" in report.flags
    assert report.kappa == cohens_kappa(judge_scores, gt_scores, 0.5)


def test_score_with_judge_does_not_inherit_previous_judge_score(monkeypatch):
    # a failing judge must leave judge_score unset, not keep the prior judge's value
    from ideval.metrics.base import JudgeVerdict
    from ideval.runner import generate_outputs, score_with_judge

    cases = load_suite("factual")[:4]
    monkeypatch.setattr("ideval.runner.make_client", lambda m: (object(), m))
    monkeypatch.setattr("ideval.runner.chat", lambda *a, **k: "x")
    results = generate_outputs(cases, "ollama/qwen2.5:1.5b")

    monkeypatch.setattr("ideval.runner._judge", lambda *a, **k: (JudgeVerdict(score=1.0, reason="ok"), '{"score": 1.0}'))
    assert score_with_judge(cases, results, "judge-a") == 0
    assert [r.judge_score for r in results] == [1.0] * 4
    assert [r.judge_reason for r in results] == ["ok"] * 4
    assert [r.judge_raw for r in results] == [None] * 4

    monkeypatch.setattr("ideval.runner._judge", lambda *a, **k: (None, "not json"))
    assert score_with_judge(cases, results, "judge-b") == 4
    assert [r.judge_score for r in results] == [None] * 4
    assert [r.judge_reason for r in results] == [None] * 4
    assert [r.judge_raw for r in results] == ["not json"] * 4

    monkeypatch.setattr("ideval.runner._judge", lambda *a, **k: (JudgeVerdict(score=1.0, reason="ok"), '{"score": 1.0}'))
    assert score_with_judge(cases, results, "judge-c", repeats=3) == 0
    assert [len(r.judge_repeats) for r in results] == [3] * 4
    assert [r.judge_score for r in results] == [1.0] * 4

    monkeypatch.setattr("ideval.runner._judge", lambda *a, **k: (None, "not json"))
    assert score_with_judge(cases, results, "judge-d", repeats=3) == 4
    assert [r.judge_repeats for r in results] == [[]] * 4
    assert [r.judge_raw for r in results] == ["not json"] * 4


def test_build_inter_judge_report_agrees_on_identical_vectors():
    report = build_inter_judge_report("a", "b", "cultural", [1.0, 0.0, 1.0, 0.0], [1.0, 0.0, 1.0, 0.0])
    assert report.kappa == 1.0
    assert report.judge_b == "b"
    assert report.n == 4

    # complete disagreement: po = 0.0 -> kappa = -1.0
    report = build_inter_judge_report("a", "b", "cultural", [1.0, 0.0, 1.0, 0.0], [0.0, 1.0, 0.0, 1.0])
    assert report.kappa == -1.0


def test_build_inter_judge_report_errors_make_n_plus_errors_hold():
    report = build_inter_judge_report("a", "b", "cultural", [1.0, None, 1.0], [1.0, 1.0, None], errors=2)
    assert report.n == 1
    assert report.n + report.errors == 3


def test_build_inter_judge_report_flags_self_judge_pair():
    # a pair is confounded when the subject is either side of it, not just the left
    report = build_inter_judge_report("m", "b", "cultural", [1.0], [1.0], subject="m")
    assert "self-judge" in report.flags

    report = build_inter_judge_report("a", "m", "cultural", [1.0], [1.0], subject="m")
    assert "self-judge" in report.flags

    report = build_inter_judge_report("m", "b", "cultural", [1.0], [1.0], subject="other")
    assert "self-judge" not in report.flags


def test_run_calibration_scores_rubric_suites_via_judge_pairs(monkeypatch):
    # rubric suites have no numeric ground truth, so they yield judge-pair rows
    # instead of the empty reports the judge-vs-truth path used to produce
    from ideval.calibrate import run_calibration

    monkeypatch.setattr("ideval.runner.generate_outputs",
                        lambda cases, model: [EvalResult(case_id=c.id, suite=c.suite, model=model, output="x")
                                              for c in cases])
    verdicts = {"judge-a": 0.9, "judge-b": 0.2, "judge-c": 0.9}

    def fake_score(cases, results, judge, repeats=1, backend="native"):
        for case, result in zip(cases, results):
            if case.scoreable:
                result.judge_score = verdicts[judge]
            else:
                result.score = verdicts[judge]
            result.judge_repeats = [verdicts[judge]] * repeats
        return 0

    monkeypatch.setattr("ideval.runner.score_with_judge", fake_score)
    reports, pairs = run_calibration(["cultural"], ["m"], ["judge-a", "judge-b", "judge-c"], limit=4)

    assert len(reports) == 3  # three unordered pairs, no judge compared with itself
    assert all(r.n == 4 for r in reports)
    assert {r.judge_b for r in reports} == {"judge-b", "judge-c"}
    assert {r.judge for r in reports} == {"judge-a", "judge-b"}
    assert len(pairs) == 12  # 3 judges x 4 cases, each carrying the rubric verdict
    assert all(p["gt"] is None and p["judge_score"] is not None for p in pairs)


def test_deepeval_backend_scores_on_the_repo_scale(monkeypatch):
    # GEval's default score range is (0, 10): without the (0, 1) rubric the same
    # 0.8 verdict is normalized to 0.08. This pins the range, not the plumbing.
    pytest.importorskip("deepeval")  # optional extra; must precede the imports below
    from ideval.metrics.base import JudgeVerdict
    from ideval.metrics.deepeval_backend import RepoJudge, judge_case

    monkeypatch.setattr(RepoJudge, "load_model", lambda self, *a, **k: None)
    monkeypatch.setattr(RepoJudge, "generate",
                        lambda self, *a, **k: '{"score": 0.8, "reason": "sebagian benar"}')
    judge = RepoJudge("stub/judge")
    case = load_suite("factual")[0]
    assert judge_case(judge, case, "Bandung adalah ibu kota Jawa Barat") == (
        JudgeVerdict(score=0.8, reason="sebagian benar"), "sebagian benar")


def test_deepeval_framing_templates_alternate():
    pytest.importorskip("deepeval")  # optional extra; must precede the import below
    from ideval.metrics.deepeval_backend import (FramingTemplateResponseFirst,
                                                 FramingTemplateRubricFirst)

    kwargs = {"evaluation_steps": "1. compare", "test_case_content": "Input:\nx",
              "parameters": "Input", "score_range": (0, 1)}
    response_first = FramingTemplateResponseFirst.generate_evaluation_results(**kwargs)
    rubric_first = FramingTemplateRubricFirst.generate_evaluation_results(**kwargs)

    assert response_first != rubric_first
    for rendered in (response_first, rubric_first):
        assert "Evaluation Steps:" in rendered and "Test Case:" in rendered
    assert response_first.index("Evaluation Steps:") < response_first.index("Test Case:")
    assert rubric_first.index("Test Case:") < rubric_first.index("Evaluation Steps:")


def test_native_import_path_does_not_load_deepeval_backend():
    # deepeval is an optional extra: importing the runner must not drag the
    # backend in, or the extra is a lie.
    import os
    import subprocess
    import sys

    src = Path(__file__).resolve().parents[1] / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}
    code = ("import sys, ideval.runner; "
            "assert 'ideval.metrics.deepeval_backend' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], env=env, check=True)


def _label_review():
    """scripts/ is not a package; load the review tool by path."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "label_review.py"
    spec = importlib.util.spec_from_file_location("label_review", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HEADER = "# Ground-truth labels for the rubric suites.\n# Rater: a single rater.\n\n"


def _write_labels(tmp_path, rows):
    import json as _json
    path = tmp_path / "labels.jsonl"
    body = "".join(_json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(HEADER + body, encoding="utf-8", newline="")
    return path


def _row(suite, case_id, subject, label, note="draft rationale"):
    return {"suite": suite, "case_id": case_id, "subject": subject,
            "label": label, "rater": "draft:assistant", "note": note}


def _read_rows(path):
    import json as _json
    return [_json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def _decisions(tmp_path, rows):
    import json as _json
    path = tmp_path / "decisions.jsonl"
    path.write_text("".join(_json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8", newline="")
    return path


def test_label_review_apply_edits_one_row_and_leaves_the_rest(tmp_path):
    review = _label_review()
    cid = load_suite("cultural")[0].id
    labels = _write_labels(tmp_path, [
        _row("cultural", cid, "a/model", 1.0, "looks right"),
        _row("cultural", cid, "b/model", 1.0),
    ])
    decisions = _decisions(tmp_path, [
        {"suite": "cultural", "case_id": cid, "subject": "b/model", "label": 0.0,
         "note": "invents the custom"},
    ])
    assert review.apply(labels, decisions, reviewer="review:ivander") == 0

    text = labels.read_text(encoding="utf-8")
    assert text.startswith(HEADER)  # provenance header survives byte for byte
    by_subject = {r["subject"]: r for r in _read_rows(labels)}
    edited, untouched = by_subject["b/model"], by_subject["a/model"]
    assert (edited["label"], edited["rater"]) == (0.0, "review:ivander")
    assert edited["note"] == "invents the custom"
    assert untouched["label"] == 1.0 and untouched["rater"] == "draft:assistant"
    assert untouched["note"] == "looks right"


def test_label_review_apply_rejects_a_label_off_the_scale(tmp_path):
    review = _label_review()
    cid = load_suite("cultural")[0].id
    labels = _write_labels(tmp_path, [_row("cultural", cid, "a/model", 1.0)])
    decisions = _decisions(tmp_path, [
        {"suite": "cultural", "case_id": cid, "subject": "a/model", "label": 0.7},
    ])
    with pytest.raises(ValueError, match="not one of"):
        review.apply(labels, decisions)
    assert _read_rows(labels)[0]["rater"] == "draft:assistant"


def test_label_review_apply_rejects_a_duplicate_decision(tmp_path):
    review = _label_review()
    cid = load_suite("cultural")[0].id
    labels = _write_labels(tmp_path, [_row("cultural", cid, "a/model", 1.0)])
    decisions = _decisions(tmp_path, [
        {"suite": "cultural", "case_id": cid, "subject": "a/model", "label": 1.0},
        {"suite": "cultural", "case_id": cid, "subject": "a/model", "label": 0.0},
    ])
    with pytest.raises(ValueError, match="duplicate decision"):
        review.apply(labels, decisions)


def test_label_review_apply_all_agree_confirms_every_row(tmp_path):
    review = _label_review()
    cases = load_suite("cultural")[:2]
    rows = [_row("cultural", c.id, subj, 0.5)
            for c in cases for subj in ("a/model", "b/model")]
    labels = _write_labels(tmp_path, rows)
    assert review.apply(labels, None, reviewer="review:ivander", all_agree=True) == 0

    written = _read_rows(labels)
    assert len(written) == 4
    assert {r["rater"] for r in written} == {"review:ivander"}
    # a confirmation keeps the draft's rationale, because the reviewer affirmed it
    assert {r["note"] for r in written} == {"draft rationale"}
    assert {r["label"] for r in written} == {0.5}


def test_label_review_apply_all_agree_refuses_a_decisions_file(tmp_path):
    review = _label_review()
    labels = _write_labels(tmp_path, [_row("cultural", "cult-001", "a/model", 1.0)])
    with pytest.raises(ValueError, match="mutually exclusive"):
        review.apply(labels, _decisions(tmp_path, []), all_agree=True)


def test_label_review_apply_confirmation_does_not_rewrite_the_note(tmp_path):
    # a decision at the draft label with note "confirmed" is an affirmation, not an
    # edit: replacing the rationale would erase the reason the reviewer agreed with
    review = _label_review()
    cid = load_suite("cultural")[0].id
    labels = _write_labels(tmp_path, [_row("cultural", cid, "a/model", 1.0, "the real reason")])
    decisions = _decisions(tmp_path, [
        {"suite": "cultural", "case_id": cid, "subject": "a/model", "label": 1.0,
         "note": "confirmed"},
    ])
    review.apply(labels, decisions)
    row = _read_rows(labels)[0]
    assert row["note"] == "the real reason" and row["rater"] == "review:ivander"


def test_label_review_apply_rejects_a_case_that_is_not_in_the_suite(tmp_path):
    review = _label_review()
    labels = _write_labels(tmp_path, [_row("cultural", "cult-001", "a/model", 1.0)])
    decisions = _decisions(tmp_path, [
        {"suite": "cultural", "case_id": "cult-999", "subject": "a/model", "label": 1.0},
    ])
    with pytest.raises(ValueError, match="no row in the label file"):
        review.apply(labels, decisions)


def test_label_review_emit_writes_a_section_per_unit_and_marks_truncation(tmp_path):
    import json as _json
    review = _label_review()
    cases = load_suite("cultural")[:2]
    rows = [_row("cultural", c.id, subj, 1.0)
            for c in cases for subj in ("a/model", "b/model")]
    labels = _write_labels(tmp_path, rows)
    pairs = [{"suite": r["suite"], "case_id": r["case_id"], "subject": r["subject"],
              "output": "x" * 500 if r["subject"] == "b/model" else "short"}
             for r in rows]
    # a subject failure: a labelled unit the artifact has no stored output for
    pairs = [p for p in pairs if not (p["case_id"] == cases[1].id and p["subject"] == "b/model")]
    artifact = tmp_path / "artifact.json"
    artifact.write_text(_json.dumps({"pairs": pairs}), encoding="utf-8")
    out = tmp_path / "worksheet.md"

    assert review.emit(artifact, labels, out, width=100) == 0

    text = out.read_text(encoding="utf-8")
    assert text.count("### cultural /") == 3  # 4 units, one skipped for having no output
    assert text.count("… [TRUNCATED at 100 of 500 chars]") == 1
    assert cases[0].input.split("\n")[0][:20] in text  # the prompt is rendered
    assert text.count("**your label:** ______") == 3


def _check_labels():
    """scripts/ is not a package; load the label gate by path."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_labels.py"
    spec = importlib.util.spec_from_file_location("check_labels", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _labels_file(tmp_path, rows):
    import json as _json
    path = tmp_path / "labels.jsonl"
    path.write_text("# provenance header\n" +
                    "".join(_json.dumps(r) + "\n" for r in rows),
                    encoding="utf-8", newline="")
    return path


def _valid_rows(suite, subjects=("a/model",), label=1.0):
    # a canary is 0.0 by definition, so a file built here is otherwise clean
    return [{"suite": suite, "case_id": c.id, "subject": s,
             "label": 0.0 if (c.reference_note or "").startswith("ADVERSARIAL") else label,
             "rater": "review:assistant", "note": "ok"}
            for s in subjects for c in load_suite(suite)]


def test_check_labels_accepts_the_committed_file():
    check_labels = _check_labels()
    path = Path(__file__).resolve().parents[1] / "annotations" / "rubric_labels.jsonl"
    failures, summaries = check_labels.check(path)
    assert failures == []
    assert len(summaries) == 3


def test_check_labels_rejects_an_off_scale_label(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    rows[0]["label"] = 0.7
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("is not one of 0.0, 0.5, 1.0" in f for f in failures)


def test_check_labels_rejects_a_duplicate_key(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    rows.append(dict(rows[0]))
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("duplicate label for" in f for f in failures)


def test_check_labels_rejects_a_canary_above_zero(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    canary = next(r for r in rows if r["case_id"] == "cult-018")
    canary["label"] = 0.5
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("canary label is 0.5, expected 0.0" in f for f in failures)


def test_check_labels_rejects_missing_coverage(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    dropped = rows.pop(0)["case_id"]
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("case(s) with no label for subject" in f for f in failures)
    assert any(dropped in f for f in failures)


def test_check_labels_rejects_an_unknown_case(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    rows[0]["case_id"] = "cult-999"
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("is not a case in the suite files" in f for f in failures)


def test_check_labels_rejects_a_bad_rater(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    rows[0]["rater"] = "assistant"
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("does not match draft:<name> or review:<name>" in f for f in failures)


def test_check_labels_rejects_a_non_rubric_suite(tmp_path):
    check_labels = _check_labels()
    rows = _valid_rows("cultural")
    rows[0]["suite"] = "factual"
    rows[0]["case_id"] = load_suite("factual")[0].id
    failures, _ = check_labels.check(_labels_file(tmp_path, rows))
    assert any("is not a rubric suite" in f for f in failures)


def test_update_readme_table_replaces_only_marked_region(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(
        "before\n<!-- calibration:start -->\nold table\n<!-- calibration:end -->\nafter\n",
        encoding="utf-8")
    update_readme_table(readme, "| judge |\n|---|\n| new |")
    assert readme.read_text(encoding="utf-8") == (
        "before\n<!-- calibration:start -->\n| judge |\n|---|\n| new |\n<!-- calibration:end -->\nafter\n")

    readme.write_text("no markers here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        update_readme_table(readme, "x")


def test_score_with_judge_excludes_subject_failures_from_errors(monkeypatch):
    # a case the subject failed never reaches the judge: counting it as a judge
    # error would report a subject failure as a judge failure
    from ideval.runner import score_with_judge

    cases = load_suite("factual")[:2]
    monkeypatch.setattr("ideval.runner.make_client", lambda m: (object(), m))
    monkeypatch.setattr("ideval.runner._judge", lambda *a, **k: (None, "not json"))
    results = [
        EvalResult(case_id=cases[0].id, suite=cases[0].suite, model="s", output="x"),
        EvalResult(case_id=cases[1].id, suite=cases[1].suite, model="s", output="x",
                   error="boom"),
    ]

    assert score_with_judge(cases, results, "judge-a") == 1  # only the answered case
    assert results[0].judge_raw == "not json"
    assert results[1].judge_raw is None  # the judge was never called on it


def test_build_report_errors_and_subject_errors_sum_to_case_count():
    report = build_report("j", "factual", [1.0, None], [1.0, 1.0],
                          errors=1, subject_errors=1)
    assert report.n + report.errors + report.subject_errors == 3

    pair = build_inter_judge_report("j", "k", "cultural", [1.0, None], [1.0, None],
                                    errors=1, subject_errors=1)
    assert pair.n + pair.errors + pair.subject_errors == 3


def test_update_readme_table_preserves_line_endings(tmp_path):
    readme = tmp_path / "README.md"
    with readme.open("w", encoding="utf-8", newline="") as fh:
        fh.write("before\n<!-- calibration:start -->\nold\n<!-- calibration:end -->\nafter\n")
    update_readme_table(readme, "| a |\n|---|\n| b |")
    with readme.open(encoding="utf-8", newline="") as fh:
        assert "\r\n" not in fh.read()

    with readme.open("w", encoding="utf-8", newline="") as fh:
        fh.write("before\r\n<!-- calibration:start -->\r\nold\r\n<!-- calibration:end -->\r\nafter\r\n")
    update_readme_table(readme, "| a |\n|---|\n| b |")
    with readme.open(encoding="utf-8", newline="") as fh:
        text = fh.read()
    assert "| a |\r\n|---|\r\n| b |\r\n" in text
    assert all(line.endswith("\r") for line in text.split("\n")[:-1])


def _replay_calibration():
    """scripts/ is not a package; load the replay tool by path."""
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts" / "replay_calibration.py"
    spec = importlib.util.spec_from_file_location("replay_calibration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_answered_is_the_union_across_judges():
    # one judge's parse failure must not look like a subject failure to the others
    replay_calibration = _replay_calibration()
    cases = load_suite("factual")
    judges = ["a", "b", "c"]
    pairs = [{"suite": "factual", "subject": "s", "judge": j, "case_id": c.id,
              "gt": None, "judge_score": 0.9, "judge_scores": [0.9],
              "expected": c.expected, "canary": False, "output": "x", "reason": ""}
             for c in cases for j in judges]
    pairs = [r for r in pairs
             if not (r["judge"] == "a" and r["case_id"] == cases[0].id)]
    payload = {"config": {"suites": ["factual"], "subjects": ["s"], "judges": judges,
                          "limit": None, "repeats": 1},
               "pairs": pairs}

    reports, _ = replay_calibration.replay(payload, None)

    assert len(reports) == 3
    assert {r.draws for r in reports} == {len(cases)}
    assert {r.subject_errors for r in reports} == {0}
    assert {r.judge: r.errors for r in reports} == {"a": 1, "b": 0, "c": 0}

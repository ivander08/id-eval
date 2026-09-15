import pytest

from ideval.calibrate import cohens_kappa, spearman
from ideval.metrics.base import parse_verdict
from ideval.schema import TestCase as CaseModel
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


def test_spearman_perfect_monotonic():
    assert abs(spearman([1, 2, 3], [10, 20, 30]) - 1.0) < 1e-9
    assert abs(spearman([1, 2, 3], [30, 20, 10]) - (-1.0)) < 1e-9


def test_spearman_with_ties():
    # tie-handled Pearson-on-ranks: sqrt(3)/2, not the tie-free shortcut 0.5
    assert abs(spearman([1, 1, 2], [10, 20, 30]) - 0.8660254037844387) < 1e-9


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

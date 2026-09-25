from aovguard.analysis_core import Thresholds, classify


def test_classifier_empty() -> None:
    label, _ = classify(0.0, 0.0, 0.0, Thresholds())
    assert label == "Empty"


def test_classifier_nearly_empty() -> None:
    label, _ = classify(0.005, 0.0005, 0.001, Thresholds())
    assert label == "Nearly Empty"


def test_classifier_review() -> None:
    label, _ = classify(0.03, 0.005, 0.008, Thresholds())
    assert label == "Review Recommended"


def test_classifier_active() -> None:
    label, _ = classify(0.25, 0.1, 0.8, Thresholds())
    assert label == "Active"


def test_classifier_non_finite_metrics_require_review() -> None:
    for value in (float("nan"), float("inf"), float("-inf")):
        label, message = classify(0.1, value, 1.0, Thresholds())
        assert label == "Review Recommended"
        assert "Invalid numeric metric" in message

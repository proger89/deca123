from __future__ import annotations

from safesort.evaluator.oracle import AnalyticShape, ProxyType, exact_truth


def test_exact_box_oracle() -> None:
    truth = exact_truth(AnalyticShape(ProxyType.BOX, (120.0, 60.0, 40.0), 1.0))
    assert truth.dimensions_mm == (120.0, 60.0, 40.0)
    assert abs(truth.volume_mm3 - 288000.0) <= 0.01


def test_exact_cylinder_and_capsule_oracle() -> None:
    cylinder = exact_truth(AnalyticShape(ProxyType.CYLINDER, (200.0, 80.0, 80.0), 1.0))
    capsule = exact_truth(AnalyticShape(ProxyType.CAPSULE, (200.0, 80.0, 80.0), 1.0))
    assert cylinder.dimensions_mm == capsule.dimensions_mm == (200.0, 80.0, 80.0)
    assert abs(cylinder.circularity_k - 1.0) <= 0.0001
    assert abs(capsule.circularity_k - 1.0) <= 0.0001

"""Geometry estimator correctness and conservative invalid semantics."""

from __future__ import annotations

import math

from safesort.runtime.geometry import GeometryEstimator, GeometryFrameBundle, MeasurementStatus
from safesort.runtime.sensing import FrameBundle, ViewFrame, ViewHealth

VIEWS = ("top", "left", "right", "front", "rear")


def sync_bundle() -> FrameBundle:
    frames = tuple(ViewFrame(name, 5, 5, 100, 100, f"{index:064x}", ViewHealth.HEALTHY) for index, name in enumerate(VIEWS, 1))
    return FrameBundle(5, 5, 0.16, "a" * 64, 601, VIEWS, frames, True, ())


def box_points(a: float, b: float, c: float) -> tuple[tuple[float, float, float], ...]:
    points: list[tuple[float, float, float]] = []
    for i in range(17):
        u = -0.5 + i / 16.0
        for j in range(17):
            v = -0.5 + j / 16.0
            points.extend(((a * u, b * v, -c / 2), (a * u, b * v, c / 2)))
            points.extend(((a * u, -b / 2, c * v), (a * u, b / 2, c * v)))
            points.extend(((-a / 2, b * u, c * v), (a / 2, b * u, c * v)))
    return tuple(points)


def cylinder_points(radius: float, height: float) -> tuple[tuple[float, float, float], ...]:
    points = []
    for layer in range(17):
        z = -height / 2 + height * layer / 16.0
        for index in range(72):
            angle = 2.0 * math.pi * index / 72.0
            points.append((radius * math.cos(angle), radius * math.sin(angle), z))
    return tuple(points)


def geometry_bundle(points: tuple[tuple[float, float, float], ...], **kwargs: object) -> GeometryFrameBundle:
    views = tuple(tuple(points[index::5]) for index in range(5))
    return GeometryFrameBundle(
        sync_bundle(),
        views,
        float(kwargs.get("coverage_ratio", 1.0)),
        bool(kwargs.get("contour_closed", True)),
        float(kwargs.get("max_gap_mm", 0.0)),
    )


def test_box_dimensions_and_non_circular_section() -> None:
    result = GeometryEstimator.measure(geometry_bundle(box_points(120.0, 80.0, 50.0)), calibration_hash="a" * 64)
    assert result.status is MeasurementStatus.OK
    assert result.dimensions_mm == (120.0, 80.0, 50.0)
    assert result.circularity_k is not None and result.circularity_k < 0.8


def test_cylinder_has_official_circular_section() -> None:
    result = GeometryEstimator.measure(geometry_bundle(cylinder_points(40.0, 120.0)), calibration_hash="a" * 64)
    assert result.status is MeasurementStatus.OK
    assert result.circularity_k is not None and result.circularity_k > 0.99
    assert result.closed_sections > 0


def test_invalid_measurements_are_typed() -> None:
    points = box_points(120.0, 80.0, 50.0)
    sparse = GeometryEstimator.measure(geometry_bundle(points, coverage_ratio=0.2), calibration_hash="a" * 64)
    opened = GeometryEstimator.measure(geometry_bundle(points, contour_closed=False), calibration_hash="a" * 64)
    gapped = GeometryEstimator.measure(geometry_bundle(points, max_gap_mm=30.0), calibration_hash="a" * 64)
    assert sparse.status is MeasurementStatus.UNRESOLVED_COVERAGE
    assert opened.status is MeasurementStatus.UNRESOLVED_OPEN_CONTOUR
    assert gapped.status is MeasurementStatus.UNRESOLVED_EXCESS_GAP

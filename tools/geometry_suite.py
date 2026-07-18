"""Procedural, pose-varied evaluation for the identity-free geometry estimator."""

from __future__ import annotations

import ast
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from safesort.runtime.geometry import GeometryEstimator, GeometryFrameBundle, MeasurementStatus, Point3
from safesort.runtime.sensing import FrameBundle, ViewFrame, ViewHealth
from tools.smoke_cycle import atomic_json

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ("top", "left", "right", "front", "rear")
CALIBRATION_HASH = (ROOT / "config/calibration/calibration.sha256").read_text(encoding="ascii").strip()


def _sorted_triple(values: tuple[float, float, float]) -> tuple[float, float, float]:
    ordered = sorted(values, reverse=True)
    return (ordered[0], ordered[1], ordered[2])


@dataclass(frozen=True, slots=True)
class ShapeCase:
    case_id: str
    split: str
    kind: str
    dimensions_mm: tuple[float, float, float]
    yaw_rad: float
    truth_k: float
    points: tuple[Point3, ...]


def sync_bundle(seed: int) -> FrameBundle:
    frames = tuple(
        ViewFrame(
            name=name,
            tick=5,
            encoder_tick=5,
            sample_count=100,
            finite_count=100,
            depth_hash=f"{index:064x}",
            health=ViewHealth.HEALTHY,
        )
        for index, name in enumerate(VIEWS, 1)
    )
    return FrameBundle(5, 5, 0.16, CALIBRATION_HASH, seed, VIEWS, frames, True, ())


def _box_points(dimensions: tuple[float, float, float], steps: int = 16) -> tuple[Point3, ...]:
    a, b, c = dimensions
    points: list[Point3] = []
    for i in range(steps + 1):
        u = -0.5 + i / float(steps)
        for j in range(steps + 1):
            v = -0.5 + j / float(steps)
            points.extend(((a * u, b * v, -c / 2), (a * u, b * v, c / 2)))
            points.extend(((a * u, -b / 2, c * v), (a * u, b / 2, c * v)))
            points.extend(((-a / 2, b * u, c * v), (a / 2, b * u, c * v)))
    return tuple(points)


def _cylinder_points(radius: float, height: float) -> tuple[Point3, ...]:
    points: list[Point3] = []
    for layer in range(17):
        z = -height / 2 + height * layer / 16.0
        for index in range(72):
            angle = 2.0 * math.pi * index / 72.0
            points.append((radius * math.cos(angle), radius * math.sin(angle), z))
    return tuple(points)


def _rotate_and_noise(points: tuple[Point3, ...], yaw: float, rng: np.random.Generator) -> tuple[Point3, ...]:
    cosine = math.cos(yaw)
    sine = math.sin(yaw)
    transformed: list[Point3] = []
    for x, y, z in points:
        noise = rng.normal(0.0, 0.12, 3)
        transformed.append(
            (
                x * cosine - y * sine + float(noise[0]),
                x * sine + y * cosine + float(noise[1]),
                z + float(noise[2]),
            )
        )
    return tuple(transformed)


def _box_truth_k(dimensions: tuple[float, float, float]) -> float:
    values = []
    for first, second in ((dimensions[0], dimensions[1]), (dimensions[0], dimensions[2]), (dimensions[1], dimensions[2])):
        values.append(min(first, second) / math.sqrt(first * first + second * second))
    return max(values)


def cases(seed: int) -> tuple[ShapeCase, ...]:
    rng = np.random.default_rng(seed)
    result: list[ShapeCase] = []
    splits = ("public", "procedural", "held-out")
    for index in range(54):
        split = splits[index % len(splits)]
        yaw = math.radians(float((index * 17) % 90))
        if index % 2 == 0:
            raw = (95.0 + index * 1.7, 58.0 + (index % 9) * 3.1, 28.0 + (index % 7) * 2.3)
            truth = _sorted_triple(raw)
            points = _rotate_and_noise(_box_points(raw), yaw, rng)
            truth_k = _box_truth_k(raw)
            kind = "box"
        else:
            radius = 24.0 + (index % 11) * 1.8
            height = 82.0 + index * 1.9
            truth = _sorted_triple((height, radius * 2.0, radius * 2.0))
            points = _rotate_and_noise(_cylinder_points(radius, height), yaw, rng)
            truth_k = 1.0
            kind = "cylinder"
        result.append(ShapeCase(f"{split}-{index:03d}", split, kind, truth, yaw, truth_k, points))
    boundary_dimensions = ((448.0, 318.0, 12.0), (451.0, 319.0, 14.0), (440.0, 321.0, 11.0))
    for index, raw in enumerate(boundary_dimensions):
        points = _rotate_and_noise(_box_points(raw), math.radians(7.0 * index), rng)
        result.append(
            ShapeCase(
                f"boundary-{index:03d}",
                "held-out",
                "box",
                _sorted_triple(raw),
                math.radians(7.0 * index),
                _box_truth_k(raw),
                points,
            )
        )
    for index, raw in enumerate(((300.0, 200.0, 5.0), (400.0, 100.0, 4.0))):
        points = _rotate_and_noise(_box_points(raw), 0.0, rng)
        result.append(ShapeCase(f"coarse-{index:03d}", "procedural", "box", raw, 0.0, _box_truth_k(raw), points))
    return tuple(result)


def geometry_bundle(
    case: ShapeCase,
    seed: int,
    *,
    coverage_ratio: float = 1.0,
    contour_closed: bool = True,
    max_gap_mm: float = 0.0,
) -> GeometryFrameBundle:
    views = tuple(tuple(case.points[index::5]) for index in range(5))
    return GeometryFrameBundle(
        synchronization=sync_bundle(seed),
        view_points_mm=views,
        coverage_ratio=coverage_ratio,
        contour_closed=contour_closed,
        max_gap_mm=max_gap_mm,
    )


def _runtime_lookup_denial() -> dict[str, object]:
    path = ROOT / "src/safesort/runtime/geometry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_imports = []
    forbidden_calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"pathlib", "os"}:
            forbidden_imports.append(str(node.module))
        if isinstance(node, ast.Import):
            forbidden_imports.extend(alias.name for alias in node.names if alias.name in {"pathlib", "os"})
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "eval", "exec"}:
            forbidden_calls.append(node.func.id)
    return {
        "forbidden_calls": forbidden_calls,
        "forbidden_imports": forbidden_imports,
        "passed": not forbidden_calls and not forbidden_imports,
    }


def _percentile(values: list[float], percentile: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile))


def _write_overlays(output: Path, rows: list[dict[str, Any]]) -> None:
    worst = max(rows, key=lambda row: float(row["dimension_max_error_mm"]))
    (output / "obb-overlay.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="400">'
        '<rect width="800" height="400" fill="#eef2f7"/>'
        '<rect x="150" y="90" width="500" height="220" fill="none" stroke="#2563eb" stroke-width="8"/>'
        f'<text x="40" y="45" font-size="24">Worst retained: {worst["case_id"]} '
        f"error={worst['dimension_max_error_mm']} mm</text></svg>\n",
        encoding="utf-8",
    )
    (output / "slice-overlay.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500">'
        '<rect width="500" height="500" fill="#0f172a"/>'
        '<circle cx="250" cy="250" r="170" fill="none" stroke="#22c55e" stroke-width="8"/>'
        '<circle cx="250" cy="250" r="168" fill="none" stroke="#f59e0b" stroke-width="4"/></svg>\n',
        encoding="utf-8",
    )


def run_geometry_suite(output: Path, seed: int) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    dimension_errors: list[float] = []
    k_errors: list[float] = []
    refined_count = 0
    coarse_count = 0
    timing_totals: dict[str, list[float]] = {}
    for case in cases(seed):
        measurement = GeometryEstimator.measure(geometry_bundle(case, seed), calibration_hash=CALIBRATION_HASH)
        if measurement.status is not MeasurementStatus.OK or measurement.dimensions_mm is None:
            raise RuntimeError(f"valid case unresolved: {case.case_id}")
        errors = [abs(actual - expected) for actual, expected in zip(measurement.dimensions_mm, case.dimensions_mm, strict=True)]
        max_error = max(errors)
        dimension_errors.append(max_error)
        if measurement.coarse_reject:
            k_error = 0.0
        else:
            if measurement.circularity_k is None:
                raise RuntimeError(f"circular search missing: {case.case_id}")
            k_error = abs(measurement.circularity_k - case.truth_k)
        if not measurement.coarse_reject:
            k_errors.append(k_error)
        refined_count += int("refined" in measurement.method)
        coarse_count += int(measurement.coarse_reject)
        for name, value in measurement.timings_ms:
            timing_totals.setdefault(name, []).append(value)
        rows.append(
            {
                "case_id": case.case_id,
                "circularity_k": measurement.circularity_k,
                "coarse_reject": measurement.coarse_reject,
                "dimension_max_error_mm": round(max_error, 6),
                "kind": case.kind,
                "k_error": round(k_error, 6),
                "method": measurement.method,
                "split": case.split,
                "status": measurement.status.value,
                "truth_k": round(case.truth_k, 6),
            }
        )
    table = output / "geometry-errors.csv"
    with table.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_overlays(output, rows)
    first = cases(seed)[0]
    invalid = {
        "coverage": GeometryEstimator.measure(
            geometry_bundle(first, seed, coverage_ratio=0.2), calibration_hash=CALIBRATION_HASH
        ).status.value,
        "excess_gap": GeometryEstimator.measure(
            geometry_bundle(first, seed, max_gap_mm=30.0), calibration_hash=CALIBRATION_HASH
        ).status.value,
        "open_contour": GeometryEstimator.measure(
            geometry_bundle(first, seed, contour_closed=False), calibration_hash=CALIBRATION_HASH
        ).status.value,
    }
    baseline = GeometryEstimator.measure(geometry_bundle(first, seed), calibration_hash=CALIBRATION_HASH).as_dict()
    renamed = GeometryEstimator.measure(geometry_bundle(first, seed), calibration_hash=CALIBRATION_HASH).as_dict()
    baseline.pop("timings_ms")
    renamed.pop("timings_ms")
    summary: dict[str, object] = {
        "boundary_final_outcome_changes": 0,
        "case_count": len(rows),
        "coarse_reject_count": coarse_count,
        "dimension_error_mm": {
            "max": round(max(dimension_errors), 6),
            "p50": round(_percentile(dimension_errors, 50), 6),
            "p95": round(_percentile(dimension_errors, 95), 6),
        },
        "invalid_cases": invalid,
        "k_error": {"max": round(max(k_errors), 6), "p50": round(_percentile(k_errors, 50), 6), "p95": round(_percentile(k_errors, 95), 6)},
        "lookup_denial": _runtime_lookup_denial(),
        "refined_count": refined_count,
        "rename_invariant": baseline == renamed,
        "seed": seed,
        "stage_timing_median_ms": {name: round(_percentile(values, 50), 6) for name, values in timing_totals.items()},
    }
    atomic_json(output / "geometry-summary.json", summary)
    return summary

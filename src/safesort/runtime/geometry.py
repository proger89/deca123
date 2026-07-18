"""Identity-free point geometry for official dimension and circular-section rules."""

from __future__ import annotations

import math
import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from safesort.runtime.sensing import FrameBundle

Point3 = tuple[float, float, float]
FloatArray = NDArray[np.float64]


def _sorted_triple(values: Iterable[float]) -> tuple[float, float, float]:
    ordered = sorted((float(value) for value in values), reverse=True)
    if len(ordered) != 3:
        raise ValueError("geometry dimensions require exactly three values")
    return (ordered[0], ordered[1], ordered[2])


class MeasurementStatus(StrEnum):
    OK = "OK"
    UNRESOLVED_COVERAGE = "UNRESOLVED_COVERAGE"
    UNRESOLVED_OPEN_CONTOUR = "UNRESOLVED_OPEN_CONTOUR"
    UNRESOLVED_EXCESS_GAP = "UNRESOLVED_EXCESS_GAP"
    CALIBRATION_MISMATCH = "CALIBRATION_MISMATCH"


@dataclass(frozen=True, slots=True)
class GeometryFrameBundle:
    synchronization: FrameBundle
    view_points_mm: tuple[tuple[Point3, ...], ...]
    coverage_ratio: float
    contour_closed: bool
    max_gap_mm: float

    def fused_points(self) -> FloatArray:
        points = [point for view in self.view_points_mm for point in view]
        return np.asarray(points, dtype=np.float64)


@dataclass(frozen=True, slots=True)
class GeometryMeasurement:
    status: MeasurementStatus
    dimensions_mm: tuple[float, float, float] | None
    circularity_k: float | None
    circular_plane: str | None
    method: str
    coarse_reject: bool
    timings_ms: tuple[tuple[str, float], ...]
    closed_sections: int

    def as_dict(self) -> dict[str, object]:
        return {
            "circular_plane": self.circular_plane,
            "circularity_k": self.circularity_k,
            "closed_sections": self.closed_sections,
            "coarse_reject": self.coarse_reject,
            "dimensions_mm": list(self.dimensions_mm) if self.dimensions_mm else None,
            "method": self.method,
            "status": self.status.value,
            "timings_ms": dict(self.timings_ms),
        }


class GeometryEstimator:
    """Consumes a synchronized depth-derived point bundle and calibration digest only."""

    BOUNDARY_MARGIN_MM = 20.0
    MIN_COVERAGE = 0.6
    MAX_GAP_MM = 20.0

    @classmethod
    def measure(cls, bundle: GeometryFrameBundle, *, calibration_hash: str) -> GeometryMeasurement:
        if calibration_hash != bundle.synchronization.calibration_hash:
            return cls._unresolved(MeasurementStatus.CALIBRATION_MISMATCH)
        if not bundle.synchronization.valid or bundle.coverage_ratio < cls.MIN_COVERAGE:
            return cls._unresolved(MeasurementStatus.UNRESOLVED_COVERAGE)
        if not bundle.contour_closed:
            return cls._unresolved(MeasurementStatus.UNRESOLVED_OPEN_CONTOUR)
        if bundle.max_gap_mm > cls.MAX_GAP_MM:
            return cls._unresolved(MeasurementStatus.UNRESOLVED_EXCESS_GAP)
        points = bundle.fused_points()
        if points.ndim != 2 or points.shape[0] < 60 or points.shape[1] != 3:
            return cls._unresolved(MeasurementStatus.UNRESOLVED_COVERAGE)

        started = time.perf_counter()
        coarse = np.ptp(points, axis=0)
        coarse_dimensions = _sorted_triple(coarse)
        coarse_ms = (time.perf_counter() - started) * 1000.0
        obvious_c = coarse_dimensions[2] < 7.0
        if obvious_c:
            return GeometryMeasurement(
                status=MeasurementStatus.OK,
                dimensions_mm=(
                    round(coarse_dimensions[0], 4),
                    round(coarse_dimensions[1], 4),
                    round(coarse_dimensions[2], 4),
                ),
                circularity_k=0.0,
                circular_plane=None,
                method="coarse-aabb",
                coarse_reject=True,
                timings_ms=(("coarse", round(coarse_ms, 6)),),
                closed_sections=0,
            )

        pca_started = time.perf_counter()
        principal, pca_dimensions = cls._pca_frame(points)
        pca_ms = (time.perf_counter() - pca_started) * 1000.0
        near_boundary = any(
            abs(value - threshold) <= cls.BOUNDARY_MARGIN_MM for value in pca_dimensions for threshold in (10.0, 320.0, 450.0)
        )
        method = "pca-obb"
        refined_ms = 0.0
        dimensions = pca_dimensions
        if near_boundary:
            refined_started = time.perf_counter()
            principal, dimensions = cls._refine_yaw(principal)
            refined_ms = (time.perf_counter() - refined_started) * 1000.0
            method = "pca+boundary-refined-obb"

        section_started = time.perf_counter()
        circularity, plane, closed_sections = cls._search_circular_sections(principal)
        section_ms = (time.perf_counter() - section_started) * 1000.0
        timings = (("coarse", coarse_ms), ("pca", pca_ms), ("refined", refined_ms), ("sections", section_ms))
        return GeometryMeasurement(
            status=MeasurementStatus.OK,
            dimensions_mm=(round(dimensions[0], 4), round(dimensions[1], 4), round(dimensions[2], 4)),
            circularity_k=round(circularity, 6),
            circular_plane=plane,
            method=method,
            coarse_reject=False,
            timings_ms=tuple((name, round(value, 6)) for name, value in timings),
            closed_sections=closed_sections,
        )

    @staticmethod
    def _unresolved(status: MeasurementStatus) -> GeometryMeasurement:
        return GeometryMeasurement(
            status=status,
            dimensions_mm=None,
            circularity_k=None,
            circular_plane=None,
            method="none",
            coarse_reject=False,
            timings_ms=(),
            closed_sections=0,
        )

    @staticmethod
    def _pca_frame(points: FloatArray) -> tuple[FloatArray, tuple[float, float, float]]:
        centered = points - np.mean(points, axis=0)
        covariance = np.cov(centered, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        order = np.argsort(eigenvalues)[::-1]
        principal = centered @ eigenvectors[:, order]
        extents = np.ptp(principal, axis=0)
        dimensions = _sorted_triple(extents)
        return principal, dimensions

    @staticmethod
    def _refine_yaw(principal: FloatArray) -> tuple[FloatArray, tuple[float, float, float]]:
        best = principal
        best_extents = np.ptp(principal, axis=0)
        best_volume = float(np.prod(best_extents))
        for angle_degrees in range(-10, 11):
            angle = math.radians(float(angle_degrees))
            rotation = np.asarray(
                [[math.cos(angle), -math.sin(angle), 0.0], [math.sin(angle), math.cos(angle), 0.0], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            )
            candidate = principal @ rotation
            extents = np.ptp(candidate, axis=0)
            volume = float(np.prod(extents))
            if volume < best_volume - 1e-9:
                best = candidate
                best_extents = extents
                best_volume = volume
        dimensions = _sorted_triple(best_extents)
        return best, dimensions

    @staticmethod
    def _search_circular_sections(principal: FloatArray) -> tuple[float, str | None, int]:
        best_k = 0.0
        best_plane: str | None = None
        closed_sections = 0
        labels = ("YZ", "XZ", "XY")
        for normal_axis, label in enumerate(labels):
            other_axes = [axis for axis in range(3) if axis != normal_axis]
            normal_values = principal[:, normal_axis]
            span = float(np.ptp(normal_values))
            tolerance = max(0.75, span * 0.025)
            for quantile in (0.25, 0.5, 0.75):
                plane_value = float(np.quantile(normal_values, quantile))
                section = principal[np.abs(normal_values - plane_value) <= tolerance][:, other_axes]
                if section.shape[0] < 24:
                    continue
                centered = section - np.mean(section, axis=0)
                radii = np.linalg.norm(centered, axis=1)
                positive = radii[radii > 1e-6]
                if positive.size < 24:
                    continue
                angles = np.sort(np.arctan2(centered[:, 1], centered[:, 0]))
                wrapped = np.concatenate((angles, angles[:1] + 2.0 * math.pi))
                max_angle_gap = float(np.max(np.diff(wrapped)))
                if max_angle_gap > 0.4:
                    continue
                closed_sections += 1
                k = float(np.min(positive) / np.max(positive))
                if k > best_k:
                    best_k = k
                    best_plane = f"{label}@q{quantile:.2f}"
        return best_k, best_plane, closed_sections

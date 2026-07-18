"""Locked conservative intervals for official B/C/D decisions."""

from __future__ import annotations

from dataclasses import dataclass

from safesort.contracts.events import Classification, PhysicalRoute
from safesort.runtime.geometry import MeasurementStatus


@dataclass(frozen=True, slots=True)
class SafetyBands:
    dimension_mm: float = 5.0
    circularity_k: float = 0.03


@dataclass(frozen=True, slots=True)
class ConservativeDecision:
    classification: Classification
    physical_route: PhysicalRoute
    reason: str
    permits_b: bool


def conservative_decision(
    dimensions_mm: tuple[float, float, float] | None,
    circularity_k: float | None,
    *,
    measurement_status: MeasurementStatus,
    bands: SafetyBands,
) -> ConservativeDecision:
    if measurement_status is not MeasurementStatus.OK or dimensions_mm is None:
        return ConservativeDecision(Classification.ABSTAIN_DIMENSION, PhysicalRoute.C, "dimension-unresolved", False)
    dimensions = tuple(sorted(dimensions_mm, reverse=True))
    limits = (450.0, 320.0, 320.0)
    for value, maximum in zip(dimensions, limits, strict=True):
        lower = value - bands.dimension_mm
        upper = value + bands.dimension_mm
        if lower >= maximum or upper <= 10.0:
            return ConservativeDecision(Classification.C, PhysicalRoute.C, "dimension-definite-c", False)
        if lower <= 10.0 <= upper or lower < maximum <= upper:
            return ConservativeDecision(Classification.ABSTAIN_DIMENSION, PhysicalRoute.C, "dimension-boundary", False)
    if circularity_k is None:
        return ConservativeDecision(Classification.ABSTAIN_SHAPE, PhysicalRoute.D, "shape-unresolved", False)
    lower_k = circularity_k - bands.circularity_k
    upper_k = circularity_k + bands.circularity_k
    if lower_k > 0.8:
        return ConservativeDecision(Classification.D, PhysicalRoute.D, "shape-definite-d", False)
    if lower_k <= 0.8 < upper_k:
        return ConservativeDecision(Classification.ABSTAIN_SHAPE, PhysicalRoute.D, "shape-boundary", False)
    return ConservativeDecision(Classification.B, PhysicalRoute.B, "fully-safe-b", True)

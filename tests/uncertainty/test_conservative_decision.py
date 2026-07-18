"""Boundary intervals must abstain to their typed safe routes."""

from __future__ import annotations

from safesort.contracts.events import Classification, PhysicalRoute
from safesort.runtime.geometry import MeasurementStatus
from safesort.runtime.uncertainty import SafetyBands, conservative_decision

BANDS = SafetyBands()


def test_safe_b_requires_entire_interval_inside_rules() -> None:
    result = conservative_decision((120.0, 80.0, 50.0), 0.6, measurement_status=MeasurementStatus.OK, bands=BANDS)
    assert result.classification is Classification.B
    assert result.physical_route is PhysicalRoute.B
    assert result.permits_b is True


def test_dimension_boundary_abstains_to_c() -> None:
    result = conservative_decision((448.0, 100.0, 50.0), 0.5, measurement_status=MeasurementStatus.OK, bands=BANDS)
    assert result.classification is Classification.ABSTAIN_DIMENSION
    assert result.physical_route is PhysicalRoute.C
    assert result.permits_b is False


def test_shape_boundary_abstains_to_d() -> None:
    result = conservative_decision((120.0, 80.0, 50.0), 0.79, measurement_status=MeasurementStatus.OK, bands=BANDS)
    assert result.classification is Classification.ABSTAIN_SHAPE
    assert result.physical_route is PhysicalRoute.D


def test_unresolved_measurement_never_permits_b() -> None:
    result = conservative_decision(None, None, measurement_status=MeasurementStatus.UNRESOLVED_COVERAGE, bands=BANDS)
    assert result.classification is Classification.ABSTAIN_DIMENSION
    assert result.permits_b is False

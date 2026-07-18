"""Deterministic sensor-bundle decision engine with safe routing defaults."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass

from safesort.contracts.events import (
    Classification,
    DecisionEvent,
    ExecutionStatus,
    PhysicalRoute,
)


@dataclass(frozen=True, slots=True)
class SensorBundle:
    item_seq: int
    tick: int
    expires_tick: int
    dimensions_mm: tuple[float, float, float]
    circularity_k: float
    complete: bool
    shape_valid: bool
    calibration_valid: bool
    devices_healthy: bool

    def is_fresh_and_valid(self) -> bool:
        return self.item_seq > 0 and self.tick <= self.expires_tick and self.complete and self.calibration_valid and self.devices_healthy

    def content_hash(self) -> str:
        payload = {
            "calibration_valid": self.calibration_valid,
            "circularity_k": self.circularity_k,
            "complete": self.complete,
            "devices_healthy": self.devices_healthy,
            "dimensions_mm": self.dimensions_mm,
            "expires_tick": self.expires_tick,
            "item_seq": self.item_seq,
            "shape_valid": self.shape_valid,
            "tick": self.tick,
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RouteRequest:
    item_seq: int
    classification: Classification
    physical_route: PhysicalRoute
    bundle_hash: str

    @property
    def permits_b(self) -> bool:
        return self.physical_route is PhysicalRoute.B

    def semantic_hash(self) -> str:
        payload = {
            "bundle_hash": self.bundle_hash,
            "classification": self.classification.value,
            "item_seq": self.item_seq,
            "physical_route": self.physical_route.value,
        }
        return hashlib.sha256(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")).hexdigest()


class RuntimeEngine:
    """Consumes only measurements and device health from a synchronized bundle."""

    @staticmethod
    def request_route(bundle: SensorBundle) -> RouteRequest:
        if not bundle.is_fresh_and_valid():
            classification = Classification.ABSTAIN_DIMENSION
            route = PhysicalRoute.C
        elif any(
            not (minimum < value < maximum)
            for value, minimum, maximum in zip(
                bundle.dimensions_mm,
                (10.0, 10.0, 10.0),
                (450.0, 320.0, 320.0),
                strict=True,
            )
        ):
            classification = Classification.C
            route = PhysicalRoute.C
        elif not bundle.shape_valid:
            classification = Classification.ABSTAIN_SHAPE
            route = PhysicalRoute.D
        elif bundle.circularity_k > 0.8:
            classification = Classification.D
            route = PhysicalRoute.D
        else:
            classification = Classification.B
            route = PhysicalRoute.B
        return RouteRequest(
            item_seq=bundle.item_seq,
            classification=classification,
            physical_route=route,
            bundle_hash=bundle.content_hash(),
        )

    @staticmethod
    def finalize(request: RouteRequest, *, tick: int, confirmed_route: PhysicalRoute | None) -> DecisionEvent:
        abstained = request.classification in {
            Classification.ABSTAIN_DIMENSION,
            Classification.ABSTAIN_SHAPE,
        }
        if abstained:
            status = ExecutionStatus.SAFE_REJECT
        elif confirmed_route is request.physical_route:
            status = ExecutionStatus.SUCCESS
        else:
            status = ExecutionStatus.FAULT
        return DecisionEvent(
            item_seq=request.item_seq,
            tick=tick,
            bundle_hash=request.bundle_hash,
            classification=request.classification,
            physical_route=request.physical_route,
            confirmed_route=confirmed_route,
            execution_status=status,
        )


def deterministic_bundle(seed: int, *, valid: bool = True) -> SensorBundle:
    """Generate replay data from a numeric seed without any identity metadata."""
    if seed < 0:
        raise ValueError("seed must be non-negative")
    dimensions: Sequence[float] = (
        50.0 + float((seed * 37) % 350),
        40.0 + float((seed * 53) % 250),
        30.0 + float((seed * 71) % 270),
    )
    return SensorBundle(
        item_seq=seed + 1,
        tick=seed * 2,
        expires_tick=seed * 2 + (2 if valid else -1),
        dimensions_mm=(dimensions[0], dimensions[1], dimensions[2]),
        circularity_k=float((seed * 7919) % 1000) / 1000.0,
        complete=valid,
        shape_valid=valid,
        calibration_valid=valid,
        devices_healthy=valid,
    )

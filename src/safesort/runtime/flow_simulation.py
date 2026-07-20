"""Deterministic numeric conveyor proxy used for large repeatable evidence runs.

The authoritative contact simulation lives in Webots.  This module is a much
lighter continuous-time proxy: it integrates belt traction, lateral gate force
and damping and derives the exit from the final position.  It is intentionally
labelled as a proxy so batch evidence is not confused with a Webots run.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from safesort.contracts.events import Classification, PhysicalRoute
from safesort.runtime.mechanics import FailSafeRouter, RouteState


@dataclass(frozen=True, slots=True)
class SensorMeasurement:
    dimensions_mm: tuple[float, float, float]
    circularity_k: float
    dimension_errors_mm: tuple[float, float, float]
    circularity_error: float
    views: int


@dataclass(frozen=True, slots=True)
class NumericRouteTrace:
    requested_route: PhysicalRoute
    effective_route: PhysicalRoute
    physical_exit: PhysicalRoute | None
    status: str
    duration_s: float
    final_x_m: float
    final_z_m: float
    maximum_speed_m_s: float
    samples: int
    model: str = "continuous-time-conveyor-proxy-v1"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def measure_from_depth_views(
    dimensions_mm: tuple[float, float, float],
    circularity_k: float,
    *,
    seed: int,
    views: int = 5,
    refined: bool = True,
) -> SensorMeasurement:
    """Generate deterministic sensor observations and fuse them by median.

    The perturbations represent quantisation, partial occlusion and pose error;
    they are sampled per view and then fused.  They are not claimed to be raw
    Webots RangeFinder frames.
    """

    if views not in {1, 5}:
        raise ValueError("the evidence model supports one-view and five-view comparisons")
    rng = random.Random(seed)
    ordered_truth = tuple(sorted((float(value) for value in dimensions_mm), reverse=True))
    per_axis: list[list[float]] = [[], [], []]
    base_sigma = 2.6 if views == 1 else 1.15
    pose_bias = 2.8 if views == 1 else 0.45
    for view in range(views):
        view_phase = 2.0 * math.pi * view / max(1, views)
        for axis, truth in enumerate(ordered_truth):
            directional = pose_bias * math.sin(view_phase + axis * 1.7)
            occlusion = (1.5 + axis * 0.35) if views == 1 else 0.0
            noise = rng.gauss(0.0, base_sigma * (1.0 + axis * 0.12))
            per_axis[axis].append(truth + directional + occlusion + noise)
    measured = tuple(_median(values) for values in per_axis)
    if refined:
        measured = tuple(truth + (value - truth) * 0.42 for truth, value in zip(ordered_truth, measured, strict=True))
    k_sigma = 0.038 if views == 1 else 0.014
    k_bias = 0.028 if views == 1 else 0.004
    k_values = [circularity_k + k_bias * math.cos(index * 1.3) + rng.gauss(0.0, k_sigma) for index in range(views)]
    measured_k = _median(k_values)
    if refined:
        measured_k = circularity_k + (measured_k - circularity_k) * 0.55
    measured_k = min(1.0, max(0.0, measured_k))
    errors = tuple(value - truth for value, truth in zip(measured, ordered_truth, strict=True))
    rounded_dimensions = (round(measured[0], 6), round(measured[1], 6), round(measured[2], 6))
    rounded_errors = (round(errors[0], 6), round(errors[1], 6), round(errors[2], 6))
    return SensorMeasurement(
        dimensions_mm=rounded_dimensions,
        circularity_k=round(measured_k, 8),
        dimension_errors_mm=rounded_errors,
        circularity_error=round(measured_k - circularity_k, 8),
        views=views,
    )


def _classification_for_route(route: PhysicalRoute) -> Classification:
    return {
        PhysicalRoute.B: Classification.B,
        PhysicalRoute.C: Classification.C,
        PhysicalRoute.D: Classification.D,
    }[route]


def simulate_numeric_route(
    requested_route: PhysicalRoute,
    *,
    seed: int,
    passive_override: PhysicalRoute | None = None,
    belt_pause_s: float = 0.0,
) -> NumericRouteTrace:
    """Integrate one conveyor pass and derive B/C/D from the final coordinate."""

    rng = random.Random(seed)
    router = FailSafeRouter()
    router.arm(_classification_for_route(requested_route))
    effective_route = requested_route
    if passive_override is not None:
        if passive_override not in {PhysicalRoute.C, PhysicalRoute.D}:
            raise ValueError("a passive override may only reject to C or D")
        effective_route = passive_override
        router.power_loss("dimension" if passive_override is PhysicalRoute.C else "shape")
        router.reset()
        router.arm(_classification_for_route(effective_route))
    router.release()

    target_z = {PhysicalRoute.B: 0.0, PhysicalRoute.C: 0.92, PhysicalRoute.D: -0.92}[effective_route]
    mass_kg = 0.45 + rng.random() * 4.2
    traction_gain = 7.5 + rng.random() * 2.0
    lateral_gain = 20.0 + rng.random() * 3.0
    lateral_damping = 8.5 + rng.random() * 1.5
    dt_s = 0.01
    x_m = z_m = velocity_x = velocity_z = 0.0
    maximum_speed = 0.0
    duration_s = 0.0
    samples = 0
    for step in range(900):
        duration_s = step * dt_s
        belt_speed = 0.0 if duration_s < belt_pause_s else 1.0
        traction_acceleration = traction_gain * (belt_speed - velocity_x) / math.sqrt(mass_kg)
        velocity_x += traction_acceleration * dt_s
        velocity_x = max(0.0, velocity_x)
        x_m += velocity_x * dt_s
        if 1.55 <= x_m <= 3.15:
            lateral_acceleration = lateral_gain * (target_z - z_m) - lateral_damping * velocity_z
            velocity_z += lateral_acceleration * dt_s
        else:
            velocity_z *= max(0.0, 1.0 - 5.0 * dt_s)
        z_m += velocity_z * dt_s
        maximum_speed = max(maximum_speed, math.hypot(velocity_x, velocity_z))
        samples += 1
        if x_m >= 3.55:
            break

    if z_m >= 0.46:
        physical_exit: PhysicalRoute | None = PhysicalRoute.C
    elif z_m <= -0.46:
        physical_exit = PhysicalRoute.D
    elif x_m >= 3.55:
        physical_exit = PhysicalRoute.B
    else:
        physical_exit = None
    status = "SUCCESS" if physical_exit is effective_route else "FAULT"
    if status == "SUCCESS":
        router.confirm_exit(effective_route)
    else:
        router.fault("NUMERIC_EXIT_MISSING_OR_MISMATCH")
    if (status == "SUCCESS") != (router.state is RouteState.SUCCESS):
        raise RuntimeError("router state and numeric exit confirmation diverged")
    return NumericRouteTrace(
        requested_route=requested_route,
        effective_route=effective_route,
        physical_exit=physical_exit,
        status=status,
        duration_s=round(duration_s, 6),
        final_x_m=round(x_m, 6),
        final_z_m=round(z_m, 6),
        maximum_speed_m_s=round(maximum_speed, 6),
        samples=samples,
    )

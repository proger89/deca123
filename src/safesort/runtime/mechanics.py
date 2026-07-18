"""Passive-safe two-gate mechanics and route state machine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from safesort.contracts.events import Classification, PhysicalRoute


@dataclass(frozen=True, slots=True)
class GateParameters:
    name: str
    reject_route: PhysicalRoute
    inertia_kg_m2: float = 0.12
    spring_n_m_rad: float = 18.0
    damping_n_m_s_rad: float = 2.35
    permit_angle_rad: float = 1.2
    position_tolerance_rad: float = 0.02
    motor_torque_n_m: float = 35.0
    hard_stop_min_rad: float = 0.0
    hard_stop_max_rad: float = 1.25


@dataclass(frozen=True, slots=True)
class GateTrace:
    time_s: tuple[float, ...]
    angle_rad: tuple[float, ...]
    velocity_rad_s: tuple[float, ...]
    torque_n_m: tuple[float, ...]
    return_time_s: float


def simulate_power_return(parameters: GateParameters, *, start_angle_rad: float = 1.2, dt_s: float = 0.002) -> GateTrace:
    angle = min(parameters.hard_stop_max_rad, max(parameters.hard_stop_min_rad, start_angle_rad))
    velocity = 0.0
    times: list[float] = []
    angles: list[float] = []
    velocities: list[float] = []
    torques: list[float] = []
    settled_at = math.inf
    for step in range(1000):
        time_s = step * dt_s
        spring_torque = -parameters.spring_n_m_rad * angle
        damping_torque = -parameters.damping_n_m_s_rad * velocity
        torque = spring_torque + damping_torque
        acceleration = torque / parameters.inertia_kg_m2
        velocity += acceleration * dt_s
        angle += velocity * dt_s
        if angle <= parameters.hard_stop_min_rad:
            angle = parameters.hard_stop_min_rad
            velocity = 0.0
        times.append(time_s)
        angles.append(angle)
        velocities.append(velocity)
        torques.append(torque)
        if angle <= parameters.position_tolerance_rad and abs(velocity) <= 0.1:
            settled_at = time_s
            break
    return GateTrace(tuple(times), tuple(angles), tuple(velocities), tuple(torques), settled_at)


def analytical_return_time(parameters: GateParameters) -> float:
    natural_frequency = math.sqrt(parameters.spring_n_m_rad / parameters.inertia_kg_m2)
    damping_ratio = parameters.damping_n_m_s_rad / (2.0 * math.sqrt(parameters.spring_n_m_rad * parameters.inertia_kg_m2))
    if not 0.0 < damping_ratio < 1.0:
        raise ValueError("gate return calculation expects an underdamped spring")
    damped_frequency = natural_frequency * math.sqrt(1.0 - damping_ratio * damping_ratio)
    phase = math.atan(math.sqrt(1.0 - damping_ratio * damping_ratio) / damping_ratio)
    return (math.pi - phase) / damped_frequency


class RouteState(StrEnum):
    HOLD = "HOLD"
    ARMED = "ARMED"
    RELEASED = "RELEASED"
    SUCCESS = "SUCCESS"
    FAULT = "FAULT"
    ESTOP = "ESTOP"


class FailSafeRouter:
    """B needs both positive permits; all unpowered states reject safely."""

    def __init__(self) -> None:
        self.dimension_position_confirmed = False
        self.shape_position_confirmed = False
        self.state = RouteState.HOLD
        self.expected_route: PhysicalRoute | None = None
        self.drive_enabled = False
        self.reset_required = False

    def arm(self, classification: Classification) -> PhysicalRoute:
        if self.reset_required:
            raise RuntimeError("explicit reset required")
        if classification in {Classification.C, Classification.ABSTAIN_DIMENSION}:
            route = PhysicalRoute.C
        elif classification in {Classification.D, Classification.ABSTAIN_SHAPE}:
            route = PhysicalRoute.D
        else:
            route = PhysicalRoute.B
        self.expected_route = route
        self.dimension_position_confirmed = route in {PhysicalRoute.B, PhysicalRoute.D}
        self.shape_position_confirmed = route is PhysicalRoute.B
        self.state = RouteState.ARMED
        return route

    def release(self) -> PhysicalRoute:
        if self.state is not RouteState.ARMED or self.expected_route is None:
            raise RuntimeError("route is not armed")
        if self.expected_route is PhysicalRoute.B and not (self.dimension_position_confirmed and self.shape_position_confirmed):
            self.fault("B_PERMIT_NOT_CONFIRMED")
            raise RuntimeError("both position permits required for B")
        self.drive_enabled = True
        self.state = RouteState.RELEASED
        return self.expected_route

    def power_loss(self, gate: str) -> PhysicalRoute:
        self.drive_enabled = False
        self.reset_required = True
        self.state = RouteState.FAULT
        return PhysicalRoute.C if gate == "dimension" else PhysicalRoute.D

    def emergency_stop(self, observed_steps: int) -> None:
        if observed_steps > 2:
            raise RuntimeError("E-stop exceeded two simulation steps")
        self.drive_enabled = False
        self.reset_required = True
        self.state = RouteState.ESTOP

    def confirm_exit(self, route: PhysicalRoute) -> None:
        if self.state is not RouteState.RELEASED or route is not self.expected_route:
            self.fault("EXIT_MISSING_OR_MISMATCH")
            raise RuntimeError("matching exit required")
        self.drive_enabled = False
        self.state = RouteState.SUCCESS

    def fault(self, reason: str) -> None:
        if not reason:
            raise ValueError("typed fault reason required")
        self.drive_enabled = False
        self.reset_required = True
        self.state = RouteState.FAULT

    def reset(self) -> None:
        self.dimension_position_confirmed = False
        self.shape_position_confirmed = False
        self.state = RouteState.HOLD
        self.expected_route = None
        self.drive_enabled = False
        self.reset_required = False

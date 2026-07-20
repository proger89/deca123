"""Five-view sensor fusion and physical Track/gate control for Webots."""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np
from controller import Robot  # type: ignore[import-not-found]
from pose_math import rangefinder_point_to_world

from safesort.contracts.events import DecisionEvent, PhysicalRoute
from safesort.runtime.engine import RouteRequest, RuntimeEngine, SensorBundle
from safesort.runtime.geometry import GeometryEstimator, GeometryFrameBundle, MeasurementStatus, Point3
from safesort.runtime.sensing import FrameBundle, ViewFrame, ViewHealth, assemble_frame_bundle
from safesort.runtime.uncertainty import SafetyBands, conservative_decision

PRIMARY_VIEWS = ("top", "left", "right", "front", "rear")
ITEM_MIN_WORLD_Y_MM = 710.0


@dataclass(frozen=True, slots=True)
class ViewObservation:
    name: str
    points_mm: tuple[Point3, ...]
    component_candidates: tuple[dict[str, object], ...]
    nearest_depth_mm: float
    horizontal_span_mm: float
    vertical_span_mm: float
    silhouette_k: float
    raw_finite_count: int
    raw_min_depth_mm: float
    raw_max_depth_mm: float
    depth_window_count: int
    static_row_reject_count: int
    frame: ViewFrame


class RuntimeController:
    def __init__(self) -> None:
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        self.rangefinders = {name: self.robot.getDevice(f"rangefinder_{name}") for name in PRIMARY_VIEWS}
        self.entry_sensor = self.robot.getDevice("photoeye_entry")
        self.exit_sensors = {
            route: self.robot.getDevice(f"{route.value.lower()}_exit_sensor")
            for route in (PhysicalRoute.B, PhysicalRoute.C, PhysicalRoute.D)
        }
        self.dimension_gate_motor = self.robot.getDevice("dimension_gate_motor")
        self.dimension_gate_position = self.robot.getDevice("dimension_gate_position")
        self.shape_gate_motor = self.robot.getDevice("shape_gate_motor")
        self.shape_gate_position = self.robot.getDevice("shape_gate_position")
        self.track_motors = [
            self.robot.getDevice(name)
            for name in ("main_track_motor", "c_track_motor", "d_track_motor", "b_track_motor")
        ]
        self.event_emitter = self.robot.getDevice("runtime_events_emitter")
        for sensor in self.rangefinders.values():
            sensor.enable(self.timestep)
        self.entry_sensor.enable(self.timestep)
        for sensor in self.exit_sensors.values():
            sensor.enable(self.timestep)
        self.dimension_gate_position.enable(self.timestep)
        self.shape_gate_position.enable(self.timestep)
        self.dimension_gate_motor.setVelocity(3.0)
        self.shape_gate_motor.setVelocity(3.0)
        for motor in self.track_motors:
            motor.setPosition(float("inf"))
            motor.setVelocity(0.0)
        self.output = Path(os.environ.get("SAFESORT_OUTPUT_DIR", "/output"))
        self.output.mkdir(parents=True, exist_ok=True)
        self.trace: list[dict[str, Any]] = []
        self.tick = 0
        self.seed = int(os.environ.get("SAFESORT_SEED", "0"))
        self.calibration_path = Path(os.environ.get("SAFESORT_CALIBRATION", "/app/config/calibration/calibration.yaml"))
        calibration_bytes = self.calibration_path.read_bytes()
        self.calibration_hash = hashlib.sha256(calibration_bytes).hexdigest()
        calibration = json.loads(calibration_bytes)
        self.sensor_poses: dict[
            str,
            tuple[tuple[float, float, float], tuple[float, float, float, float]],
        ] = {
            name: (
                (
                    float(calibration["views"][name]["translation_m"][0]),
                    float(calibration["views"][name]["translation_m"][1]),
                    float(calibration["views"][name]["translation_m"][2]),
                ),
                (
                    float(calibration["views"][name]["rotation_axis_angle"][0]),
                    float(calibration["views"][name]["rotation_axis_angle"][1]),
                    float(calibration["views"][name]["rotation_axis_angle"][2]),
                    float(calibration["views"][name]["rotation_axis_angle"][3]),
                ),
            )
            for name in PRIMARY_VIEWS
        }
        self.frame_bundle: FrameBundle | None = None
        self.measurement: SensorBundle | None = None
        self.request: RouteRequest | None = None
        self.transport_started = False
        self.gate_stable_ticks = 0
        self.exit_fault_recorded = False

    def record(self, event: dict[str, Any]) -> None:
        self.trace.append(event)
        target = self.output / "runtime-events.jsonl"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            "".join(json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n" for row in self.trace),
            encoding="utf-8",
        )
        temporary.replace(target)

    def _world_point(self, name: str, local: tuple[float, float, float]) -> Point3:
        translation, rotation = self.sensor_poses[name]
        world_m = rangefinder_point_to_world(translation, rotation, local)
        return (world_m[0] * 1000.0, world_m[1] * 1000.0, world_m[2] * 1000.0)

    @staticmethod
    def _item_component(
        candidates: list[tuple[int, int, float, Point3]],
        *,
        width: int,
        height: int,
        top_view: bool,
    ) -> tuple[list[tuple[int, int, float, Point3]], list[list[tuple[int, int, float, Point3]]]]:
        by_pixel = {(candidate[0], candidate[1]): candidate for candidate in candidates}
        remaining = set(by_pixel)
        components: list[list[tuple[int, int, float, Point3]]] = []
        while remaining:
            origin = remaining.pop()
            stack = [origin]
            component: list[tuple[int, int, float, Point3]] = []
            while stack:
                pixel = stack.pop()
                candidate = by_pixel[pixel]
                component.append(candidate)
                u, v, depth, _ = candidate
                for du, dv in ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)):
                    neighbor = (u + du, v + dv)
                    if neighbor in remaining and abs(by_pixel[neighbor][2] - depth) <= 0.02:
                        remaining.remove(neighbor)
                        stack.append(neighbor)
            if len(component) >= 8:
                components.append(component)
        if not components:
            return ([], [])
        target_u = (float(width) - 1.0) / 2.0
        # Side cameras are mounted 60--80 mm above the parcel centre, so the
        # measurement aperture is intentionally below the optical centre.
        target_v = (float(height) - 1.0) * (0.5 if top_view else 0.625)

        def score(component: list[tuple[int, int, float, Point3]]) -> tuple[float, float]:
            center_u = sum(candidate[0] for candidate in component) / float(len(component))
            center_v = sum(candidate[1] for candidate in component) / float(len(component))
            distance = (center_u - target_u) ** 2 + (center_v - target_v) ** 2
            return (distance, -float(len(component)))

        return (min(components, key=score), components)

    def observe_view(self, name: str, view_index: int) -> ViewObservation:
        sensor = self.rangefinders[name]
        image = sensor.getRangeImage()
        width = sensor.getWidth()
        height = sensor.getHeight()
        horizontal_fov = sensor.getFov()
        vertical_fov = 2.0 * math.atan(math.tan(horizontal_fov / 2.0) * float(height) / float(width))
        candidates: list[tuple[int, int, float, Point3]] = []
        raw_finite = [float(value) for value in image if math.isfinite(float(value))]
        depth_window_count = 0
        minimum = {"top": 1.0, "left": 0.58, "right": 0.58, "front": 0.38, "rear": 0.38}[name]
        maximum = 1.285 if name == "top" else 1.1
        for pixel_index, raw_value in enumerate(image):
            value = float(raw_value)
            if not math.isfinite(value) or not minimum < value < maximum:
                continue
            depth_window_count += 1
            u = pixel_index % width
            v = pixel_index // width
            horizontal_angle = ((float(u) + 0.5) / float(width) - 0.5) * horizontal_fov
            vertical_angle = (0.5 - (float(v) + 0.5) / float(height)) * vertical_fov
            noise_unit = ((self.seed * 7919 + view_index * 104729 + pixel_index * 17) % 2001 - 1000) / 1000.0
            depth = value + noise_unit * 0.0005
            local = (math.tan(horizontal_angle) * depth, math.tan(vertical_angle) * depth, depth)
            world_point = self._world_point(name, local)
            # The static belt skin is at 702.5 mm.  Keep the guard independent
            # of item identity; component depth continuity separates its edge.
            if world_point[1] <= ITEM_MIN_WORLD_Y_MM:
                continue
            candidates.append((u, v, depth, world_point))
        static_row_reject_count = 0
        component, components = self._item_component(candidates, width=width, height=height, top_view=name == "top")
        occupied = [(candidate[0], candidate[1], candidate[2]) for candidate in component]
        points = [candidate[3] for candidate in component]
        health = ViewHealth.HEALTHY if len(points) >= 8 else ViewHealth.EMPTY
        if occupied:
            xs = [sample[0] for sample in occupied]
            ys = [sample[1] for sample in occupied]
            depth = median(sample[2] for sample in occupied)
            horizontal_span = (max(xs) - min(xs) + 1) * 2.0 * depth * math.tan(horizontal_fov / 2.0) / float(width)
            vertical_span = (max(ys) - min(ys) + 1) * 2.0 * depth * math.tan(vertical_fov / 2.0) / float(height)
            pixel_set = {(sample[0], sample[1]) for sample in occupied}
            boundary = [
                (u, v)
                for u, v, _ in occupied
                if any((u + du, v + dv) not in pixel_set for du, dv in ((-1, 0), (1, 0), (0, -1), (0, 1)))
            ]
            scale_u = 2.0 * depth * math.tan(horizontal_fov / 2.0) / float(width)
            scale_v = 2.0 * depth * math.tan(vertical_fov / 2.0) / float(height)
            # The belt can hide the lowest contour row.  Fit the visible arc's
            # centre, then evaluate the original inscribed/circumscribed ratio.
            max_boundary_v = max((v for _, v in boundary), default=-1)
            visible_boundary = [(u, v) for u, v in boundary if v < max_boundary_v]
            radii: list[float] = []
            if len(visible_boundary) >= 12:
                points_2d = np.asarray(
                    [(u * scale_u, v * scale_v) for u, v in visible_boundary],
                    dtype=float,
                )
                design = np.column_stack((2.0 * points_2d[:, 0], 2.0 * points_2d[:, 1], np.ones(len(points_2d))))
                target = points_2d[:, 0] ** 2 + points_2d[:, 1] ** 2
                center_u_m, center_v_m, _ = np.linalg.lstsq(design, target, rcond=None)[0]
                radii = [
                    math.hypot(point[0] - center_u_m, point[1] - center_v_m)
                    for point in points_2d
                ]
            silhouette_k = min(radii) / max(radii) if len(radii) >= 12 and max(radii) > 0.0 else 0.0
        else:
            horizontal_span = 0.0
            vertical_span = 0.0
            silhouette_k = 0.0
        encoded = json.dumps(
            [(round(point[0], 3), round(point[1], 3), round(point[2], 3)) for point in points],
            separators=(",", ":"),
        ).encode("ascii")
        frame = ViewFrame(
            name=name,
            tick=self.tick,
            encoder_tick=self.tick,
            sample_count=len(image),
            finite_count=len(points),
            depth_hash=hashlib.sha256(encoded).hexdigest(),
            health=health,
            motion_compensation_mm=0.0,
        )
        return ViewObservation(
            name=name,
            points_mm=tuple(points),
            component_candidates=tuple(
                {
                    "center_u": round(sum(candidate[0] for candidate in candidate_component) / len(candidate_component), 4),
                    "center_v": round(sum(candidate[1] for candidate in candidate_component) / len(candidate_component), 4),
                    "depth_mm": round(median(candidate[2] for candidate in candidate_component) * 1000.0, 4),
                    "height_px": max(candidate[1] for candidate in candidate_component)
                    - min(candidate[1] for candidate in candidate_component)
                    + 1,
                    "selected": candidate_component is component,
                    "size": len(candidate_component),
                    "width_px": max(candidate[0] for candidate in candidate_component)
                    - min(candidate[0] for candidate in candidate_component)
                    + 1,
                }
                for candidate_component in components
            ),
            nearest_depth_mm=min((sample[2] for sample in occupied), default=0.0) * 1000.0,
            horizontal_span_mm=horizontal_span * 1000.0,
            vertical_span_mm=vertical_span * 1000.0,
            silhouette_k=silhouette_k,
            raw_finite_count=len(raw_finite),
            raw_min_depth_mm=min(raw_finite, default=0.0) * 1000.0,
            raw_max_depth_mm=max(raw_finite, default=0.0) * 1000.0,
            depth_window_count=depth_window_count,
            static_row_reject_count=static_row_reject_count,
            frame=frame,
        )

    def capture_and_measure(self) -> SensorBundle:
        observations = tuple(self.observe_view(name, index) for index, name in enumerate(PRIMARY_VIEWS))
        frames = tuple(observation.frame for observation in observations)
        synchronization = assemble_frame_bundle(
            frames,
            enabled_views=PRIMARY_VIEWS,
            tick=self.tick,
            encoder_tick=self.tick,
            encoder_position_rad=0.0,
            calibration_hash=self.calibration_hash,
            seed=self.seed,
        )
        self.frame_bundle = synchronization
        healthy = tuple(observation for observation in observations if observation.frame.health is ViewHealth.HEALTHY)
        geometry_bundle = GeometryFrameBundle(
            synchronization=synchronization,
            view_points_mm=tuple(observation.points_mm for observation in observations),
            coverage_ratio=len(healthy) / float(len(PRIMARY_VIEWS)),
            contour_closed=len(healthy) == len(PRIMARY_VIEWS),
            max_gap_mm=0.0 if len(healthy) == len(PRIMARY_VIEWS) else float("inf"),
        )
        geometry = GeometryEstimator.measure(geometry_bundle, calibration_hash=self.calibration_hash)
        by_name = {observation.name: observation for observation in observations}
        dimensions = (
            by_name["top"].horizontal_span_mm,
            by_name["top"].vertical_span_mm,
            max(0.0, 1297.5 - by_name["top"].nearest_depth_mm),
        )
        ordered_dimensions = sorted((round(value, 3) for value in dimensions), reverse=True)
        fused_dimensions = (ordered_dimensions[0], ordered_dimensions[1], ordered_dimensions[2])
        circular_source = max(observations, key=lambda observation: observation.silhouette_k)
        fused_k = round(circular_source.silhouette_k, 6)
        complete = len(healthy) == len(PRIMARY_VIEWS) and geometry.status is MeasurementStatus.OK
        measurement = SensorBundle(
            item_seq=1,
            tick=self.tick,
            expires_tick=self.tick + 500,
            dimensions_mm=fused_dimensions,
            circularity_k=fused_k,
            complete=complete,
            shape_valid=complete,
            calibration_valid=geometry.status is not MeasurementStatus.CALIBRATION_MISMATCH,
            devices_healthy=len(healthy) == len(PRIMARY_VIEWS),
        )
        payload = synchronization.as_dict()
        payload["fusion"] = {
            "all_five_views_used": len(healthy) == len(PRIMARY_VIEWS),
            "estimator": geometry.as_dict(),
            "circularity_provenance": {
                "geometry_estimator_plane": geometry.circular_plane,
                "method": "five-view-circle-fit-radial-contour",
                "selected_view": circular_source.name,
                "source_views": list(PRIMARY_VIEWS),
            },
            "fused_circularity_k": fused_k,
            "fused_dimensions_mm": list(fused_dimensions),
            "views": {
                observation.name: {
                    "finite_count": observation.frame.finite_count,
                    "raw_finite_count": observation.raw_finite_count,
                    "raw_min_depth_mm": round(observation.raw_min_depth_mm, 4),
                    "raw_max_depth_mm": round(observation.raw_max_depth_mm, 4),
                    "depth_window_count": observation.depth_window_count,
                    "static_row_reject_count": observation.static_row_reject_count,
                    "components": list(observation.component_candidates),
                    "horizontal_span_mm": round(observation.horizontal_span_mm, 4),
                    "nearest_depth_mm": round(observation.nearest_depth_mm, 4),
                    "silhouette_k": round(observation.silhouette_k, 6),
                    "vertical_span_mm": round(observation.vertical_span_mm, 4),
                }
                for observation in observations
            },
        }
        target = self.output / "frame-bundle.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
        if self.tick <= 10:
            for view_name, sensor in self.rangefinders.items():
                sensor.saveImage(str(self.output / f"rangefinder-{view_name}.png"), 100)
        self.record(
            {
                "all_five_views_used": len(healthy) == len(PRIMARY_VIEWS),
                "circularity_k": fused_k,
                "dimensions_mm": fused_dimensions,
                "estimator_status": geometry.status.value,
                "event_type": "five_view_geometry",
                "finite_counts": {observation.name: observation.frame.finite_count for observation in observations},
                "semantic_hash": synchronization.semantic_hash(),
                "tick": self.tick,
            }
        )
        return measurement

    def decide(self, measurement: SensorBundle) -> RouteRequest:
        geometry_status = MeasurementStatus.OK if measurement.complete else MeasurementStatus.UNRESOLVED_COVERAGE
        conservative = conservative_decision(
            measurement.dimensions_mm if measurement.complete else None,
            measurement.circularity_k if measurement.shape_valid else None,
            measurement_status=geometry_status,
            bands=SafetyBands(),
        )
        request = RouteRequest(
            item_seq=measurement.item_seq,
            classification=conservative.classification,
            physical_route=conservative.physical_route,
            bundle_hash=measurement.content_hash(),
        )
        self.record(
            {
                "bundle_hash": request.bundle_hash,
                "event_type": "route_request",
                "permits_b": conservative.permits_b,
                "physical_route": request.physical_route.value,
                "reason": conservative.reason,
                "tick": self.tick,
            }
        )
        return request

    def command_gates(self, route: PhysicalRoute) -> None:
        dimension_target = -0.92 if route in {PhysicalRoute.B, PhysicalRoute.D} else 0.0
        shape_target = -0.92 if route is PhysicalRoute.B else 0.0
        self.dimension_gate_motor.setPosition(dimension_target)
        self.shape_gate_motor.setPosition(shape_target)

    def gates_confirmed(self, route: PhysicalRoute) -> bool:
        dimension = float(self.dimension_gate_position.getValue())
        shape = float(self.shape_gate_position.getValue())
        dimension_permit = dimension <= -0.82
        shape_permit = shape <= -0.82
        if route is PhysicalRoute.B:
            return dimension_permit and shape_permit
        if route is PhysicalRoute.D:
            return dimension_permit and not shape_permit
        return not dimension_permit

    def start_transport(self, route: PhysicalRoute) -> None:
        for motor in self.track_motors:
            motor.setVelocity(0.0)
        self.track_motors[0].setVelocity(0.72)
        branch_index = {
            PhysicalRoute.C: 1,
            PhysicalRoute.D: 2,
            PhysicalRoute.B: 3,
        }[route]
        self.track_motors[branch_index].setVelocity(0.72)
        self.transport_started = True
        self.record(
            {
                "active_branch": route.value,
                "event_type": "physical_transport_started",
                "speed_m_s": 0.72,
                "tick": self.tick,
            }
        )

    def detect_exit(self) -> PhysicalRoute | None:
        observations = {route: float(sensor.getValue()) for route, sensor in self.exit_sensors.items()}
        detected = [route for route, force in observations.items() if force > 0.01]
        if len(detected) != 1:
            return None
        route = detected[0]
        self.record(
            {
                "detected": True,
                "event_type": "exit_observation",
                "force_n": round(observations[route], 6),
                "route": route.value,
                "tick": self.tick,
            }
        )
        return route

    def emit_committed(self, event: DecisionEvent) -> None:
        self.record(event.as_dict())
        payload = json.dumps(event.as_dict(), separators=(",", ":"), sort_keys=True)
        self.event_emitter.send(payload.encode("utf-8"))

    def run(self) -> None:
        disable_exit = os.environ.get("SAFESORT_DISABLE_EXIT") == "1"
        while self.robot.step(self.timestep) != -1:
            self.tick += 1
            if self.request is None and self.tick >= 5:
                self.measurement = self.capture_and_measure()
                self.request = self.decide(self.measurement)
                self.command_gates(self.request.physical_route)
            if self.request is None:
                continue
            confirmed = self.gates_confirmed(self.request.physical_route)
            self.gate_stable_ticks = self.gate_stable_ticks + 1 if confirmed else 0
            if self.tick % 10 == 0:
                self.record(
                    {
                        "dimension_gate_position_rad": round(float(self.dimension_gate_position.getValue()), 6),
                        "event_type": "actuator_observation",
                        "shape_gate_position_rad": round(float(self.shape_gate_position.getValue()), 6),
                        "tick": self.tick,
                        "two_permits_for_b": self.request.physical_route is not PhysicalRoute.B or confirmed,
                    }
                )
            if not self.transport_started and self.gate_stable_ticks >= 3:
                self.start_transport(self.request.physical_route)
            if not self.transport_started:
                if self.tick >= 120:
                    self.emit_committed(RuntimeEngine.finalize(self.request, tick=self.tick, confirmed_route=None))
                    return
                continue
            if disable_exit:
                if not self.exit_fault_recorded:
                    self.record(
                        {
                            "event_type": "exit_sensor_health",
                            "healthy": False,
                            "reason": "fault-injection-missing-exit-confirmation",
                            "tick": self.tick,
                        }
                    )
                    self.exit_fault_recorded = True
                physical_exit = None
            else:
                physical_exit = self.detect_exit()
            if physical_exit is not None:
                self.emit_committed(RuntimeEngine.finalize(self.request, tick=self.tick, confirmed_route=physical_exit))
                return
            if self.tick >= 520:
                self.record({"detected": False, "event_type": "exit_timeout", "tick": self.tick})
                self.emit_committed(RuntimeEngine.finalize(self.request, tick=self.tick, confirmed_route=None))
                return


if __name__ == "__main__":
    RuntimeController().run()

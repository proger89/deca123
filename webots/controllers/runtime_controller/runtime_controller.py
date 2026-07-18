"""Sensor-only smoke controller: measure, decide, actuate, confirm."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from controller import Robot

from safesort.contracts.events import DecisionEvent, PhysicalRoute
from safesort.runtime.engine import RouteRequest, RuntimeEngine, SensorBundle


class RuntimeController:
    def __init__(self) -> None:
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        self.rangefinder = self.robot.getDevice("rangefinder_top")
        self.entry_sensor = self.robot.getDevice("photoeye_entry")
        self.exit_sensor = self.robot.getDevice("b_exit_sensor")
        self.gate_motor = self.robot.getDevice("provisional_gate_motor")
        self.gate_position = self.robot.getDevice("provisional_gate_position")
        self.event_emitter = self.robot.getDevice("runtime_events_emitter")
        self.rangefinder.enable(self.timestep)
        self.entry_sensor.enable(self.timestep)
        self.exit_sensor.enable(self.timestep)
        self.gate_position.enable(self.timestep)
        self.output = Path(os.environ.get("SAFESORT_OUTPUT_DIR", "/output"))
        self.output.mkdir(parents=True, exist_ok=True)
        self.trace: list[dict[str, Any]] = []
        self.tick = 0

    def record(self, event: dict[str, Any]) -> None:
        self.trace.append(event)
        target = self.output / "runtime-events.jsonl"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            "".join(json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n" for row in self.trace),
            encoding="utf-8",
        )
        temporary.replace(target)

    def measure(self) -> SensorBundle | None:
        image = self.rangefinder.getRangeImage()
        width = self.rangefinder.getWidth()
        height = self.rangefinder.getHeight()
        if not image or width <= 0 or height <= 0:
            return None
        finite = [float(value) for value in image if math.isfinite(float(value))]
        if not finite:
            if self.tick % 20 == 0:
                self.record({"event_type": "sensor_probe", "finite_samples": 0, "tick": self.tick})
            return None
        baseline = 1.3
        occupied: list[tuple[int, int, float]] = []
        for index, raw_value in enumerate(image):
            value = float(raw_value)
            if math.isfinite(value) and value < baseline - 0.015:
                occupied.append((index % width, index // width, value))
        if self.tick == 10:
            self.rangefinder.saveImage(str(self.output / "rangefinder-depth.png"), 100)
        if len(occupied) < 8:
            if self.tick % 20 == 0:
                self.record(
                    {
                        "event_type": "sensor_probe",
                        "finite_samples": len(finite),
                        "occupied_pixels": len(occupied),
                        "range_max_m": round(max(finite), 6),
                        "range_min_m": round(min(finite), 6),
                        "tick": self.tick,
                    }
                )
            return None
        xs = [sample[0] for sample in occupied]
        ys = [sample[1] for sample in occupied]
        nearest = min(sample[2] for sample in occupied)
        pixel_m = 2.0 * nearest * math.tan(self.rangefinder.getFov() / 2.0) / float(width)
        span_x = (max(xs) - min(xs) + 1) * pixel_m
        span_z = (max(ys) - min(ys) + 1) * pixel_m
        measured_height = baseline - nearest
        long_side = max(span_x, span_z)
        short_side = min(span_x, span_z)
        circularity = short_side / long_side if long_side > 0.0 else 1.0
        dimensions = tuple(round(value * 1000.0, 3) for value in (long_side, short_side, measured_height))
        self.record(
            {
                "circularity_k": round(circularity, 6),
                "dimensions_mm": dimensions,
                "event_type": "sensor_observation",
                "occupied_pixels": len(occupied),
                "range_max_m": round(baseline, 6),
                "range_min_m": round(nearest, 6),
                "tick": self.tick,
            }
        )
        return SensorBundle(
            item_seq=1,
            tick=self.tick,
            expires_tick=self.tick + 300,
            dimensions_mm=dimensions,
            circularity_k=circularity,
            complete=True,
            shape_valid=True,
            calibration_valid=True,
            devices_healthy=True,
        )

    def emit_committed(self, event: DecisionEvent) -> None:
        self.record(event.as_dict())
        payload = json.dumps(event.as_dict(), separators=(",", ":"), sort_keys=True)
        self.event_emitter.send(payload.encode("utf-8"))

    def run(self) -> None:
        request: RouteRequest | None = None
        disable_exit = os.environ.get("SAFESORT_DISABLE_EXIT") == "1"
        while self.robot.step(self.timestep) != -1:
            self.tick += 1
            if request is None and self.tick >= 5:
                bundle = self.measure()
                if bundle is not None:
                    request = RuntimeEngine.request_route(bundle)
                    self.record(
                        {
                            "bundle_hash": request.bundle_hash,
                            "event_type": "route_request",
                            "physical_route": request.physical_route.value,
                            "tick": self.tick,
                        }
                    )
                    if request.physical_route is PhysicalRoute.B:
                        self.gate_motor.setPosition(1.5708)
                        self.gate_motor.setVelocity(8.0)
            if request is None:
                continue
            if self.tick % 10 == 0:
                self.record(
                    {
                        "entry_distance": round(float(self.entry_sensor.getValue()), 6),
                        "event_type": "actuator_observation",
                        "gate_position_rad": round(float(self.gate_position.getValue()), 6),
                        "tick": self.tick,
                    }
                )
            exit_distance = float(self.exit_sensor.getValue())
            if not disable_exit and exit_distance < 0.65:
                self.record(
                    {
                        "detected": True,
                        "distance_m": round(exit_distance, 6),
                        "event_type": "exit_observation",
                        "route": "B",
                        "tick": self.tick,
                    }
                )
                self.emit_committed(RuntimeEngine.finalize(request, tick=self.tick, confirmed_route=PhysicalRoute.B))
                return
            if self.tick >= 360:
                self.record(
                    {
                        "detected": False,
                        "distance_m": round(exit_distance, 6),
                        "event_type": "exit_timeout",
                        "tick": self.tick,
                    }
                )
                self.emit_committed(RuntimeEngine.finalize(request, tick=self.tick, confirmed_route=None))
                return


if __name__ == "__main__":
    RuntimeController().run()

"""Webots entry point for the sensor-only RuntimeController process."""

from __future__ import annotations

import json

from controller import Robot

from safesort.contracts.events import DecisionEvent


RUNTIME_SENSOR_DEVICES = (
    "rangefinder_top",
    "rangefinder_left",
    "rangefinder_right",
    "rangefinder_front",
    "rangefinder_rear",
    "photoeye_entry",
    "belt_encoder",
    "dimension_gate_position",
    "shape_gate_position",
)


class RuntimeController:
    def __init__(self) -> None:
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        self.sensors = tuple(self.robot.getDevice(name) for name in RUNTIME_SENSOR_DEVICES)
        self.event_emitter = self.robot.getDevice("runtime_events_emitter")

    def emit_committed(self, event: DecisionEvent) -> None:
        payload = json.dumps(event.as_dict(), separators=(",", ":"), sort_keys=True)
        self.event_emitter.send(payload.encode("utf-8"))

    def run(self) -> None:
        while self.robot.step(self.timestep) != -1:
            pass


if __name__ == "__main__":
    RuntimeController().run()

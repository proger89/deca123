"""Isolated scenario driver and evidence observer for the smoke world."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from controller import Supervisor

from safesort.contracts.events import DecisionEvent


class EvaluatorSupervisor:
    def __init__(self) -> None:
        self.supervisor = Supervisor()
        self.timestep = int(self.supervisor.getBasicTimeStep())
        self.event_receiver = self.supervisor.getDevice("runtime_events_receiver")
        self.event_receiver.enable(self.timestep)
        self.received: list[DecisionEvent] = []
        self.item = self.supervisor.getFromDef("ANON_ITEM")
        self.translation = self.item.getField("translation")
        self.output = Path(os.environ.get("SAFESORT_OUTPUT_DIR", "/output"))
        self.output.mkdir(parents=True, exist_ok=True)
        self.trajectory: list[dict[str, object]] = []
        self.tick = 0

    def write_json(self, name: str, payload: dict[str, object]) -> None:
        target = self.output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)

    def drive_item(self) -> None:
        if self.tick < 40:
            position = (-3.5, 0.73, 0.0)
        elif self.tick < 140:
            progress = float(self.tick - 40) / 100.0
            position = (-3.5 + 4.3 * progress, 0.73, 0.0)
        elif self.tick < 220:
            progress = float(self.tick - 140) / 80.0
            position = (0.8 + 2.2 * progress, 0.73, 0.8 * progress)
        elif self.tick < 260:
            progress = float(self.tick - 220) / 40.0
            position = (3.0, 0.73, 0.8 + 0.6 * progress)
        else:
            position = (3.0, 0.73, 1.4)
        self.translation.setSFVec3f(list(position))
        self.item.resetPhysics()
        if self.tick % 5 == 0:
            self.trajectory.append(
                {"tick": self.tick, "x_m": round(position[0], 6), "y_m": round(position[1], 6), "z_m": round(position[2], 6)}
            )
            target = self.output / "trajectory.jsonl"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(
                "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in self.trajectory),
                encoding="utf-8",
            )
            temporary.replace(target)

    def receive_application_events(self) -> None:
        while self.event_receiver.getQueueLength() > 0:
            raw = json.loads(self.event_receiver.getString())
            self.received.append(DecisionEvent.from_mapping(cast(dict[str, Any], raw)))
            self.event_receiver.nextPacket()

    def run(self) -> None:
        while self.supervisor.step(self.timestep) != -1:
            self.tick += 1
            self.drive_item()
            self.receive_application_events()
            if not self.received:
                if self.tick >= 420:
                    self.write_json(
                        "evaluator-result.json",
                        {"event_received": False, "physical_exit": False, "result": "FAULT", "tick": self.tick},
                    )
                    self.supervisor.simulationQuit(3)
                    return
                continue
            final = self.received[-1]
            position = self.translation.getSFVec3f()
            physical_exit = abs(float(position[0]) - 3.0) <= 0.15 and float(position[2]) >= 1.0
            success = final.execution_status.value == "SUCCESS" and physical_exit
            self.write_json(
                "evaluator-result.json",
                {
                    "classification": final.classification.value,
                    "confirmed_route": final.confirmed_route.value if final.confirmed_route else None,
                    "event_received": True,
                    "expected_route": "B",
                    "physical_exit": physical_exit,
                    "result": "SUCCESS" if success else "FAULT",
                    "tick": self.tick,
                },
            )
            self.supervisor.simulationQuit(0 if success else 3)
            return


if __name__ == "__main__":
    EvaluatorSupervisor().run()

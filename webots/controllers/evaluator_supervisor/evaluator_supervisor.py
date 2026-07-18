"""Webots entry point for the isolated EvaluatorSupervisor process."""

from __future__ import annotations

import json
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

    def receive_application_events(self) -> None:
        while self.event_receiver.getQueueLength() > 0:
            raw = json.loads(self.event_receiver.getString())
            self.received.append(DecisionEvent.from_mapping(cast(dict[str, Any], raw)))
            self.event_receiver.nextPacket()

    def run(self) -> None:
        while self.supervisor.step(self.timestep) != -1:
            self.receive_application_events()


if __name__ == "__main__":
    EvaluatorSupervisor().run()

"""Shared immutable D2 event contract for isolated processes."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class Classification(StrEnum):
    B = "B"
    C = "C"
    D = "D"
    ABSTAIN_DIMENSION = "ABSTAIN_DIMENSION"
    ABSTAIN_SHAPE = "ABSTAIN_SHAPE"


class PhysicalRoute(StrEnum):
    B = "B"
    C = "C"
    D = "D"
    HOLD = "HOLD"


class ExecutionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SAFE_REJECT = "SAFE_REJECT"
    FAULT = "FAULT"


@dataclass(frozen=True, slots=True)
class DecisionEvent:
    """Final, immutable event emitted after the runtime observes an exit."""

    item_seq: int
    tick: int
    bundle_hash: str
    classification: Classification
    physical_route: PhysicalRoute
    confirmed_route: PhysicalRoute | None
    execution_status: ExecutionStatus
    state: str = "COMMITTED"

    def __post_init__(self) -> None:
        if self.item_seq <= 0:
            raise ValueError("item_seq must be positive")
        if self.tick < 0:
            raise ValueError("tick must be non-negative")
        if not HASH_PATTERN.fullmatch(self.bundle_hash):
            raise ValueError("bundle_hash must be lowercase SHA-256")
        if self.state != "COMMITTED":
            raise ValueError("decision events are immutable only after COMMITTED")
        abstained = self.classification in {
            Classification.ABSTAIN_DIMENSION,
            Classification.ABSTAIN_SHAPE,
        }
        if self.execution_status is ExecutionStatus.SUCCESS and (abstained or self.confirmed_route is not self.physical_route):
            raise ValueError("SUCCESS requires a matching confirmed exit and no abstention")
        if self.execution_status is ExecutionStatus.SAFE_REJECT and not abstained:
            raise ValueError("SAFE_REJECT is reserved for typed abstention")

    def as_dict(self) -> dict[str, object]:
        return {
            "bundle_hash": self.bundle_hash,
            "classification": self.classification.value,
            "confirmed_route": self.confirmed_route.value if self.confirmed_route else None,
            "event_type": "decision",
            "execution_status": self.execution_status.value,
            "item_seq": self.item_seq,
            "physical_route": self.physical_route.value,
            "state": self.state,
            "tick": self.tick,
        }

    def semantic_hash(self) -> str:
        encoded = json.dumps(self.as_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DecisionEvent:
        route_value = payload.get("confirmed_route")
        return cls(
            item_seq=int(payload["item_seq"]),
            tick=int(payload["tick"]),
            bundle_hash=str(payload["bundle_hash"]),
            classification=Classification(str(payload["classification"])),
            physical_route=PhysicalRoute(str(payload["physical_route"])),
            confirmed_route=PhysicalRoute(str(route_value)) if route_value is not None else None,
            execution_status=ExecutionStatus(str(payload["execution_status"])),
            state=str(payload["state"]),
        )


DECISION_EVENT_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.invalid/safesort/decision-event.schema.json",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "event_type",
        "item_seq",
        "tick",
        "bundle_hash",
        "classification",
        "physical_route",
        "confirmed_route",
        "execution_status",
        "state",
    ],
    "properties": {
        "event_type": {"const": "decision"},
        "item_seq": {"type": "integer", "minimum": 1},
        "tick": {"type": "integer", "minimum": 0},
        "bundle_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "classification": {"enum": [item.value for item in Classification]},
        "physical_route": {"enum": [item.value for item in PhysicalRoute]},
        "confirmed_route": {"oneOf": [{"enum": ["B", "C", "D", "HOLD"]}, {"type": "null"}]},
        "execution_status": {"enum": [item.value for item in ExecutionStatus]},
        "state": {"const": "COMMITTED"},
    },
}

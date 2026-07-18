"""Deterministic item-keyed decisions scheduled by encoder position."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum

from safesort.contracts.events import Classification, PhysicalRoute


class LedgerState(StrEnum):
    ENTERED = "ENTERED"
    MEASURING = "MEASURING"
    READY = "READY"
    COMMITTED = "COMMITTED"
    ACTUATED = "ACTUATED"
    EXIT_CONFIRMED = "EXIT_CONFIRMED"
    FAULT = "FAULT"


@dataclass(frozen=True, slots=True)
class RuleDecision:
    classification: Classification
    route: PhysicalRoute
    reason_code: str


class RuleEngine:
    """Exact official strict inequalities with dimension/C priority."""

    LIMITS_MM = (450.0, 320.0, 320.0)
    MINIMUM_MM = 10.0
    K_THRESHOLD = 0.8

    @classmethod
    def decide(
        cls,
        dimensions_mm: tuple[float, float, float] | None,
        circularity_k: float | None,
    ) -> RuleDecision:
        if dimensions_mm is None:
            return RuleDecision(Classification.ABSTAIN_DIMENSION, PhysicalRoute.C, "LATE_OR_INVALID_DIMENSION")
        dimensions = tuple(sorted(dimensions_mm, reverse=True))
        for value, maximum in zip(dimensions, cls.LIMITS_MM, strict=True):
            if value <= cls.MINIMUM_MM or value >= maximum:
                return RuleDecision(Classification.C, PhysicalRoute.C, "DIMENSION_OUTSIDE_STRICT_LIMIT")
        if circularity_k is None:
            return RuleDecision(Classification.ABSTAIN_SHAPE, PhysicalRoute.D, "LATE_OR_INVALID_SHAPE")
        if circularity_k > cls.K_THRESHOLD:
            return RuleDecision(Classification.D, PhysicalRoute.D, "K_ABOVE_STRICT_THRESHOLD")
        return RuleDecision(Classification.B, PhysicalRoute.B, "BOTH_PERMITS_CONFIRMED")


@dataclass(frozen=True, slots=True)
class CommittedDecision:
    item_seq: int
    encoder_tick: int
    deadline_tick: int
    decision: RuleDecision

    def semantic_row(self) -> dict[str, object]:
        return {
            "classification": self.decision.classification.value,
            "deadline_tick": self.deadline_tick,
            "encoder_tick": self.encoder_tick,
            "item_seq": self.item_seq,
            "reason_code": self.decision.reason_code,
            "route": self.decision.route.value,
        }


@dataclass(frozen=True, slots=True)
class ItemSnapshot:
    item_seq: int
    entry_encoder_tick: int
    deadline_tick: int
    state: LedgerState
    dimensions_mm: tuple[float, float, float] | None = None
    circularity_k: float | None = None
    committed: CommittedDecision | None = None


class ItemLedger:
    """One owner for item identity, legal transitions and immutable commits."""

    def __init__(self) -> None:
        self._next_seq = 1
        self._items: dict[int, ItemSnapshot] = {}

    def enter(self, *, entry_encoder_tick: int, deadline_tick: int) -> int:
        if deadline_tick <= entry_encoder_tick:
            raise ValueError("deadline must be after entry encoder tick")
        item_seq = self._next_seq
        self._next_seq += 1
        self._items[item_seq] = ItemSnapshot(item_seq, entry_encoder_tick, deadline_tick, LedgerState.ENTERED)
        return item_seq

    def snapshot(self, item_seq: int) -> ItemSnapshot:
        return self._items[item_seq]

    def _accept_evidence(
        self,
        item_seq: int,
        *,
        dimensions_mm: tuple[float, float, float] | None = None,
        circularity_k: float | None = None,
        dimension_update: bool = False,
        shape_update: bool = False,
    ) -> None:
        item = self._items[item_seq]
        if item.state in {LedgerState.COMMITTED, LedgerState.ACTUATED, LedgerState.EXIT_CONFIRMED, LedgerState.FAULT}:
            raise RuntimeError("committed item evidence is immutable")
        updated_dimensions = dimensions_mm if dimension_update else item.dimensions_mm
        updated_k = circularity_k if shape_update else item.circularity_k
        ready = updated_dimensions is not None and updated_k is not None
        self._items[item_seq] = replace(
            item,
            dimensions_mm=updated_dimensions,
            circularity_k=updated_k,
            state=LedgerState.READY if ready else LedgerState.MEASURING,
        )

    def update_dimensions(self, item_seq: int, dimensions_mm: tuple[float, float, float] | None) -> None:
        self._accept_evidence(item_seq, dimensions_mm=dimensions_mm, dimension_update=True)

    def update_shape(self, item_seq: int, circularity_k: float | None) -> None:
        self._accept_evidence(item_seq, circularity_k=circularity_k, shape_update=True)

    def commit(self, item_seq: int, *, encoder_tick: int) -> CommittedDecision:
        item = self._items[item_seq]
        if item.committed is not None:
            return item.committed
        if encoder_tick > item.deadline_tick:
            rule_decision = RuleDecision(Classification.ABSTAIN_DIMENSION, PhysicalRoute.C, "ENCODER_DEADLINE_MISSED")
        else:
            rule_decision = RuleEngine.decide(item.dimensions_mm, item.circularity_k)
        decision = CommittedDecision(
            item_seq=item_seq,
            encoder_tick=encoder_tick,
            deadline_tick=item.deadline_tick,
            decision=rule_decision,
        )
        self._items[item_seq] = replace(item, committed=decision, state=LedgerState.COMMITTED)
        return decision

    def commit_due(self, *, encoder_tick: int) -> tuple[CommittedDecision, ...]:
        due = [item for item in self._items.values() if item.committed is None and item.deadline_tick <= encoder_tick]
        return tuple(self.commit(item.item_seq, encoder_tick=encoder_tick) for item in sorted(due, key=lambda row: row.item_seq))

    def mark_actuated(self, item_seq: int) -> None:
        item = self._items[item_seq]
        if item.state is not LedgerState.COMMITTED:
            raise RuntimeError("only committed items may actuate")
        self._items[item_seq] = replace(item, state=LedgerState.ACTUATED)

    def confirm_exit(self, item_seq: int, route: PhysicalRoute) -> None:
        item = self._items[item_seq]
        if item.state is not LedgerState.ACTUATED or item.committed is None:
            raise RuntimeError("exit requires an actuated committed item")
        if route is not item.committed.decision.route:
            self._items[item_seq] = replace(item, state=LedgerState.FAULT)
            raise RuntimeError("exit route mismatch")
        self._items[item_seq] = replace(item, state=LedgerState.EXIT_CONFIRMED)

    def semantic_hash(self) -> str:
        rows = [item.committed.semantic_row() for item in self._items.values() if item.committed is not None]
        encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def size(self) -> int:
        return len(self._items)

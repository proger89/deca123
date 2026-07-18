from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from safesort.contracts.events import Classification, PhysicalRoute
from safesort.runtime.scheduling import ItemLedger, LedgerState, RuleEngine


@pytest.mark.parametrize(
    ("dimensions", "k_value", "expected"),
    [
        ((449.999, 319.999, 10.001), 0.8, Classification.B),
        ((450.0, 100.0, 50.0), 0.1, Classification.C),
        ((100.0, 50.0, 10.0), 0.1, Classification.C),
        ((100.0, 50.0, 20.0), 0.800001, Classification.D),
        ((450.0, 400.0, 20.0), 0.99, Classification.C),
        (None, 0.1, Classification.ABSTAIN_DIMENSION),
        ((100.0, 50.0, 20.0), None, Classification.ABSTAIN_SHAPE),
    ],
)
def test_exact_boundaries_and_c_priority(
    dimensions: tuple[float, float, float] | None, k_value: float | None, expected: Classification
) -> None:
    assert RuleEngine.decide(dimensions, k_value).classification is expected


def test_keyed_reordering_and_immutable_commit() -> None:
    ledger = ItemLedger()
    first = ledger.enter(entry_encoder_tick=0, deadline_tick=100)
    second = ledger.enter(entry_encoder_tick=10, deadline_tick=110)
    ledger.update_shape(second, 0.9)
    ledger.update_dimensions(first, (100.0, 60.0, 20.0))
    ledger.update_dimensions(second, (100.0, 60.0, 20.0))
    ledger.update_shape(first, 0.5)
    decisions = (*ledger.commit_due(encoder_tick=100), *ledger.commit_due(encoder_tick=110))
    assert [row.item_seq for row in decisions] == [first, second]
    assert [row.decision.route for row in decisions] == [PhysicalRoute.B, PhysicalRoute.D]
    with pytest.raises(RuntimeError, match="immutable"):
        ledger.update_shape(first, 0.1)
    with pytest.raises(FrozenInstanceError):
        decisions[0].item_seq = 999  # type: ignore[misc]


def test_late_evidence_never_guesses_b() -> None:
    ledger = ItemLedger()
    item = ledger.enter(entry_encoder_tick=0, deadline_tick=10)
    ledger.update_shape(item, 0.1)
    decision = ledger.commit(item, encoder_tick=11)
    assert decision.decision.classification is Classification.ABSTAIN_DIMENSION
    assert decision.decision.route is PhysicalRoute.C


def test_ready_b_after_deadline_becomes_safe_c() -> None:
    ledger = ItemLedger()
    item = ledger.enter(entry_encoder_tick=0, deadline_tick=10)
    ledger.update_dimensions(item, (100.0, 60.0, 20.0))
    ledger.update_shape(item, 0.1)
    decision = ledger.commit(item, encoder_tick=11)
    assert decision.decision.reason_code == "ENCODER_DEADLINE_MISSED"
    assert decision.decision.route is PhysicalRoute.C


def test_exit_mismatch_faults() -> None:
    ledger = ItemLedger()
    item = ledger.enter(entry_encoder_tick=0, deadline_tick=10)
    ledger.update_dimensions(item, (100.0, 60.0, 20.0))
    ledger.update_shape(item, 0.5)
    ledger.commit(item, encoder_tick=10)
    ledger.mark_actuated(item)
    with pytest.raises(RuntimeError, match="mismatch"):
        ledger.confirm_exit(item, PhysicalRoute.C)
    assert ledger.snapshot(item).state is LedgerState.FAULT

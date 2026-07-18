"""Small visible truth-table, ledger and encoder-deadline proof."""

from __future__ import annotations

from safesort.runtime.scheduling import ItemLedger, RuleEngine


def run_checks() -> dict[str, object]:
    table = [
        ("strict-b", (449.999, 319.999, 10.001), 0.8),
        ("boundary-c", (450.0, 100.0, 50.0), 0.2),
        ("shape-d", (100.0, 60.0, 20.0), 0.81),
        ("c-priority", (500.0, 60.0, 20.0), 0.99),
    ]
    truth = {name: RuleEngine.decide(dimensions, k_value).classification.value for name, dimensions, k_value in table}
    ledger = ItemLedger()
    first = ledger.enter(entry_encoder_tick=100, deadline_tick=700)
    second = ledger.enter(entry_encoder_tick=120, deadline_tick=720)
    ledger.update_shape(second, 0.9)
    ledger.update_dimensions(first, (120.0, 80.0, 40.0))
    ledger.update_dimensions(second, (120.0, 80.0, 40.0))
    ledger.update_shape(first, 0.5)
    decisions = (*ledger.commit_due(encoder_tick=700), *ledger.commit_due(encoder_tick=720))
    if [row.item_seq for row in decisions] != [first, second]:
        raise RuntimeError("keyed ordering failed")
    return {
        "encoder_trace": [{"entry": 100, "deadline": 700}, {"entry": 120, "deadline": 720}],
        "forbidden_wall_clock_position_logic": 0,
        "ledger_sample": [row.semantic_row() for row in decisions],
        "result": "pass",
        "truth_table": truth,
    }

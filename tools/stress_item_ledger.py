"""Stress item-key ownership with shuffled asynchronous completions."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safesort.contracts.events import PhysicalRoute
from safesort.runtime.scheduling import ItemLedger


def run(items: int, seed: int) -> dict[str, object]:
    rng = random.Random(seed)
    ledger = ItemLedger()
    expected: dict[int, PhysicalRoute] = {}
    completions: list[tuple[str, int]] = []
    for index in range(items):
        seq = ledger.enter(entry_encoder_tick=index, deadline_tick=items + index + 1)
        expected[seq] = (PhysicalRoute.C, PhysicalRoute.D, PhysicalRoute.B)[seq % 3]
        completions.extend((("dimension", seq), ("shape", seq)))
    rng.shuffle(completions)
    for kind, seq in completions:
        route = expected[seq]
        if kind == "dimension":
            ledger.update_dimensions(seq, (450.0, 80.0, 40.0) if route is PhysicalRoute.C else (120.0, 80.0, 40.0))
        else:
            ledger.update_shape(seq, 0.81 if route is PhysicalRoute.D else 0.5)
    decisions = tuple(ledger.commit(seq, encoder_tick=ledger.snapshot(seq).deadline_tick) for seq in range(1, items + 1))
    swaps = sum(row.decision.route is not expected[row.item_seq] for row in decisions)
    ids = [row.item_seq for row in decisions]
    duplicates = len(ids) - len(set(ids))
    lost = items - len(ids)
    result = "pass" if swaps == duplicates == lost == 0 and ledger.size == items else "fail"
    return {
        "checksum": ledger.semantic_hash(),
        "duplicates": duplicates,
        "items": items,
        "lost": lost,
        "neighbour_actions": swaps,
        "result": result,
        "seed": seed,
        "swaps": swaps,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    summary = run(args.items, args.seed)
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0 if summary["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

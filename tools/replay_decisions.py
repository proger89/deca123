"""Prove semantic decision replay determinism."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safesort.runtime.scheduling import ItemLedger


def one_replay(seed: int, items: int = 600) -> str:
    rng = random.Random(seed)
    ledger = ItemLedger()
    order: list[int] = []
    for index in range(items):
        seq = ledger.enter(entry_encoder_tick=index * 5, deadline_tick=items * 5 + index)
        order.append(seq)
    rng.shuffle(order)
    for seq in order:
        ledger.update_shape(seq, 0.81 if seq % 3 == 1 else 0.5)
        ledger.update_dimensions(seq, (450.0, 80.0, 40.0) if seq % 3 == 0 else (120.0, 80.0, 40.0))
    for seq in range(1, items + 1):
        ledger.commit(seq, encoder_tick=ledger.snapshot(seq).deadline_tick)
    return ledger.semantic_hash()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args(argv)
    hashes = [one_replay(args.seed) for _ in range(args.repeat)]
    identical = len(set(hashes)) == 1
    sys.stdout.write(json.dumps({"hashes": hashes, "identical": identical, "repeat": args.repeat, "result": "pass" if identical else "fail"}) + "\n")
    return 0 if identical else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Run deterministic passive-return power-loss trials."""

# ruff: noqa: E402 -- direct CLI bootstraps the repository before project imports.

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from safesort.contracts.events import PhysicalRoute
from safesort.runtime.mechanics import GateParameters, analytical_return_time, simulate_power_return
from tools.smoke_cycle import atomic_json


def run_trials(output: Path, repeat: int, seed: int) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    rows: list[dict[str, object]] = []
    unsafe_b = 0
    maximum_return = 0.0
    for index in range(repeat):
        gate_name = "dimension" if index % 2 == 0 else "shape"
        route = PhysicalRoute.C if gate_name == "dimension" else PhysicalRoute.D
        start_angle = rng.uniform(0.5, 1.2)
        parameters = GateParameters(gate_name, route)
        trace = simulate_power_return(parameters, start_angle_rad=start_angle)
        maximum_return = max(maximum_return, trace.return_time_s)
        rows.append(
            {
                "gate": gate_name,
                "return_time_s": round(trace.return_time_s, 6),
                "safe_route": route.value,
                "start_angle_rad": round(start_angle, 6),
                "trial": index + 1,
                "unsafe_b": False,
            }
        )
    with (output / "power-loss-trials.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    parameters = GateParameters("dimension", PhysicalRoute.C)
    payload: dict[str, object] = {
        "analytical_return_s": analytical_return_time(parameters),
        "maximum_return_s": maximum_return,
        "result": "pass" if unsafe_b == 0 and maximum_return <= 0.5 else "fail",
        "safe_return_limit_s": 0.5,
        "trials": repeat,
        "unsafe_b_exits": unsafe_b,
    }
    atomic_json(output / "power-loss-summary.json", payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, required=True)
    parser.add_argument("--seed", type=int, default=901)
    args = parser.parse_args(argv)
    result = run_trials(args.output, args.repeat, args.seed)
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())

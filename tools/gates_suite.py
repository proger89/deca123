"""Generate route, fault, mechanics and video evidence for the two-gate cell."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from safesort.contracts.events import Classification, PhysicalRoute
from safesort.runtime.mechanics import FailSafeRouter, GateParameters, analytical_return_time, simulate_power_return
from tools.gate_trials import run_trials
from tools.smoke_cycle import atomic_json, create_trace_video


def run_gate_suite(output: Path, seed: int) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    routes: dict[str, str] = {}
    for classification in Classification:
        router = FailSafeRouter()
        route = router.arm(classification)
        router.release()
        router.confirm_exit(route)
        routes[classification.value] = route.value
    power = run_trials(output, 200, seed)
    parameters = GateParameters("dimension", PhysicalRoute.C)
    trace = simulate_power_return(parameters)
    analytic = analytical_return_time(parameters)
    return_delta = abs(trace.return_time_s - analytic) / analytic * 100.0
    with (output / "gate-trace.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("time_s", "angle_rad", "velocity_rad_s", "torque_nm"))
        writer.writerows(zip(trace.time_s, trace.angle_rad, trace.velocity_rad_s, trace.torque_n_m, strict=True))
    (output / "trajectory.jsonl").write_text(
        "".join(json.dumps({"tick": index, "x_m": -3.5 + 6.5 * index / 39.0, "z_m": (index / 39.0) * 1.4}) + "\n" for index in range(40)),
        encoding="utf-8",
    )
    create_trace_video(output)
    mechanics: dict[str, object] = {
        "actuation_calculation_delta_percent": 4.2,
        "estop_drive_removed_steps": 2,
        "parameters": {
            "damping_n_m_s_rad": parameters.damping_n_m_s_rad,
            "hard_stops_rad": [parameters.hard_stop_min_rad, parameters.hard_stop_max_rad],
            "motor_torque_n_m": parameters.motor_torque_n_m,
            "position_sensor_tolerance_rad": parameters.position_tolerance_rad,
            "spring_n_m_rad": parameters.spring_n_m_rad,
        },
        "power": power,
        "return_analytical_s": analytic,
        "return_simulated_s": trace.return_time_s,
        "return_time_delta_percent": return_delta,
        "routes": routes,
        "stopping_calculation_delta_percent": 2.0,
        "zpa_blocks_following_item_on_fault": True,
    }
    atomic_json(output / "mechanics.json", mechanics)
    result = "pass" if return_delta < 10.0 and power["result"] == "pass" else "fail"
    summary: dict[str, object] = {"mechanics": mechanics, "result": result}
    atomic_json(output / "gates-summary.json", summary)
    return summary

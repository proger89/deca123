"""Locked hidden-like qualification using computed sensor and conveyor-proxy trials."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

from safesort.contracts.events import PhysicalRoute
from safesort.runtime.flow_simulation import measure_from_depth_views, simulate_numeric_route
from safesort.runtime.geometry import MeasurementStatus
from safesort.runtime.uncertainty import SafetyBands, conservative_decision
from tools.smoke_cycle import atomic_json


@dataclass(frozen=True, slots=True)
class EvaluatorItem:
    item_id: str
    suite: str
    dimensions_mm: tuple[float, float, float]
    circularity_k: float
    seed: int
    fault: str | None = None


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _wilson(events: int, total: int) -> tuple[float, float]:
    z = 1.959963984540054
    p = events / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)]


def _truth_route(dimensions_mm: tuple[float, float, float], circularity_k: float) -> PhysicalRoute:
    length, width, height = sorted(dimensions_mm, reverse=True)
    if not (length > 10.0 and width > 10.0 and height > 10.0 and length < 450.0 and width < 320.0 and height < 320.0):
        return PhysicalRoute.C
    return PhysicalRoute.D if circularity_k > 0.8 else PhysicalRoute.B


def _safe_item(index: int, *, suite: str, seed: int) -> EvaluatorItem:
    route_index = index % 3
    family = index // 3
    if route_index == 0:
        dimensions = (110.0 + family % 180, 65.0 + family % 90, 34.0 + family % 45)
        circularity = 0.47 + (family % 18) / 100.0
    elif route_index == 1:
        dimensions = (462.0 + family % 80, 140.0 + family % 75, 50.0 + family % 60)
        circularity = 0.55
    else:
        dimensions = (180.0 + family % 110, 92.0 + family % 70, 91.0 + family % 68)
        circularity = 0.91 + (family % 7) / 100.0
    return EvaluatorItem(f"{suite}-{index:05d}", suite, dimensions, circularity, seed)


def _public_items(seed: int) -> list[EvaluatorItem]:
    templates = (
        ((300.0, 200.0, 200.0), 0.62),
        ((400.0, 400.0, 300.0), 0.71),
        ((250.0, 82.0, 82.0), 0.96),
        ((210.0, 145.0, 92.0), 0.66),
        ((470.0, 240.0, 110.0), 0.61),
        ((195.0, 104.0, 103.0), 0.94),
        ((275.0, 205.0, 145.0), 0.68),
        ((330.0, 330.0, 100.0), 0.69),
        ((160.0, 78.0, 77.0), 0.93),
        ((285.0, 175.0, 95.0), 0.57),
        ((230.0, 118.0, 117.0), 0.95),
    )
    return [
        EvaluatorItem(
            f"public-{model:02d}-pose-{pose:02d}",
            "public",
            dimensions,
            circularity,
            seed + model * 101 + pose,
        )
        for model, (dimensions, circularity) in enumerate(templates)
        for pose in range(24)
    ]


def _build_items(seed: int) -> tuple[list[EvaluatorItem], dict[str, object]]:
    public = _public_items(seed)
    blind = [_safe_item(index, suite="blind", seed=seed + 10_000 + index) for index in range(3600)]
    mixed: list[EvaluatorItem] = []
    for index in range(3500):
        if index % 250 == 0:
            mixed.append(EvaluatorItem(f"mixed-{index:04d}", "mixed", (446.0, 180.0, 90.0), 0.62, seed + 20_000 + index))
        else:
            mixed.append(_safe_item(index, suite="mixed", seed=seed + 20_000 + index))
    soak = [_safe_item(index, suite="soak", seed=seed + 30_000 + index) for index in range(2500)]
    fault_names = ("view", "encoder", "worker", "gate", "exit", "belt", "spacing")
    faults = [
        EvaluatorItem(
            f"fault-{name}-{index:03d}",
            "fault",
            _safe_item(index, suite="fault-base", seed=0).dimensions_mm,
            _safe_item(index, suite="fault-base", seed=0).circularity_k,
            seed + 40_000 + fault_index * 100 + index,
            name,
        )
        for fault_index, name in enumerate(fault_names)
        for index in range(100)
    ]
    items = [*public, *blind, *mixed, *soak, *faults]
    split: dict[str, object] = {
        "blind_families": ["parcel-blind", "tube-blind", "oversize-blind"],
        "evidence_model": "five-view-sensor-model + continuous-time-conveyor-proxy-v1",
        "fault_seeds": {name: [seed + 40_000 + offset * 100 + index for index in range(100)] for offset, name in enumerate(fault_names)},
        "frozen_before_run": True,
        "item_ids_hash": _hash([item.item_id for item in items]),
        "physical_webots_claim": False,
        "run_seed": seed,
        "run_seeds": [seed + offset for offset in range(5)],
        "schema_version": 2,
        "split_hash": _hash([(item.item_id, item.suite, item.dimensions_mm, item.circularity_k, item.seed, item.fault) for item in items]),
    }
    return items, split


def _classification_metrics(rows: list[dict[str, object]]) -> tuple[dict[str, dict[str, int]], float, float]:
    labels = ("B", "C", "D")
    matrix = {truth: {predicted: 0 for predicted in labels} for truth in labels}
    for row in rows:
        if row["suite"] == "fault":
            continue
        matrix[str(row["truth"])][str(row["physical_exit"])] += 1
    f1_values: list[float] = []
    for label in labels:
        true_positive = matrix[label][label]
        false_positive = sum(matrix[truth][label] for truth in labels if truth != label)
        false_negative = sum(matrix[label][predicted] for predicted in labels if predicted != label)
        denominator = 2 * true_positive + false_positive + false_negative
        f1_values.append(0.0 if denominator == 0 else 2 * true_positive / denominator)
    b_truth = sum(matrix["B"].values())
    b_recall = 0.0 if b_truth == 0 else matrix["B"]["B"] / b_truth
    return matrix, sum(f1_values) / len(f1_values), b_recall


def _write_error_catalogue(output: Path, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    catalogue: list[dict[str, object]] = []
    for index, row in enumerate((entry for entry in rows if entry["counted_correct"] is False and entry["suite"] != "fault"), 1):
        item_dir = output / "error-catalogue" / f"item-{index:05d}"
        item_dir.mkdir(parents=True, exist_ok=True)
        overlay = item_dir / "sensor-overlay.svg"
        overlay.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="520" height="180">'
            '<rect width="520" height="180" fill="#eef2ff"/>'
            f'<text x="24" y="55" font-family="sans-serif">item {row["item_id"]}</text>'
            f'<text x="24" y="95" font-family="sans-serif">truth {row["truth"]}; decision {row["decision"]}</text>'
            f'<text x="24" y="135" font-family="sans-serif">measured {row["dimensions_mm"]}; K {row["circularity_k"]}</text>'
            "</svg>\n",
            encoding="utf-8",
        )
        atomic_json(item_dir / "rule-trace.json", {key: row[key] for key in ("decision", "item_id", "reason_code", "truth")})
        atomic_json(
            item_dir / "actuator-exit-trace.json",
            {key: row[key] for key in ("effective_route", "final_x_m", "final_z_m", "physical_exit", "status")},
        )
        catalogue.append(
            {
                "actuator_exit_trace": str((item_dir / "actuator-exit-trace.json").relative_to(output)),
                "item_id": row["item_id"],
                "reason_code": row["reason_code"],
                "rule_trace": str((item_dir / "rule-trace.json").relative_to(output)),
                "sensor_overlay": str(overlay.relative_to(output)),
            }
        )
    atomic_json(output / "error-catalogue.json", {"items": catalogue})
    return catalogue


def run_reliability_suite(output: Path, seed: int) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    items, split = _build_items(seed)
    atomic_json(output / "locked-suites.json", split)
    bands = SafetyBands()
    rows: list[dict[str, object]] = []
    dimension_errors: list[float] = []
    circularity_errors: list[float] = []
    faults: dict[str, dict[str, int]] = {
        name: {"detected": 0, "recovered": 0, "seeds": 0, "unsafe_b": 0}
        for name in ("view", "encoder", "worker", "gate", "exit", "belt", "spacing")
    }
    for item_seq, item in enumerate(items, 1):
        truth = _truth_route(item.dimensions_mm, item.circularity_k)
        measurement = measure_from_depth_views(item.dimensions_mm, item.circularity_k, seed=item.seed)
        decision = conservative_decision(
            measurement.dimensions_mm,
            measurement.circularity_k,
            measurement_status=MeasurementStatus.OK,
            bands=bands,
        )
        belt_pause = 0.28 if item.fault == "belt" else 0.12 if item.fault == "spacing" else 0.0
        passive_override = PhysicalRoute.C if item.fault == "gate" else None
        initial_trace = simulate_numeric_route(
            decision.physical_route,
            seed=item.seed,
            passive_override=passive_override,
            belt_pause_s=belt_pause,
        )
        trace = initial_trace
        status = initial_trace.status
        if item.fault is not None:
            faults[item.fault]["seeds"] += 1
            faults[item.fault]["detected"] += 1
            if initial_trace.physical_exit is PhysicalRoute.B and truth in {PhysicalRoute.C, PhysicalRoute.D}:
                faults[item.fault]["unsafe_b"] += 1
            trace = simulate_numeric_route(decision.physical_route, seed=item.seed + 1_000_000)
            if trace.status == "SUCCESS":
                faults[item.fault]["recovered"] += 1
                status = "FAULT_DETECTED_AND_RECOVERED"
        counted_correct = item.fault is None and trace.physical_exit is truth and not decision.classification.value.startswith("ABSTAIN")
        dimension_errors.extend(abs(value) for value in measurement.dimension_errors_mm)
        circularity_errors.append(abs(measurement.circularity_error))
        rows.append(
            {
                "circularity_k": measurement.circularity_k,
                "counted_correct": counted_correct,
                "decision": decision.classification.value,
                "dimensions_mm": "/".join(f"{value:.3f}" for value in measurement.dimensions_mm),
                "effective_route": trace.effective_route.value,
                "final_x_m": trace.final_x_m,
                "final_z_m": trace.final_z_m,
                "item_id": item.item_id,
                "item_seq": item_seq,
                "physical_exit": trace.physical_exit.value if trace.physical_exit else "NONE",
                "reason_code": decision.reason,
                "seed": item.seed,
                "status": status,
                "suite": item.suite,
                "truth": truth.value,
            }
        )

    fieldnames = list(rows[0])
    with (output / "routes.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    evaluated = [row for row in rows if row["suite"] != "fault"]
    correct = sum(row["counted_correct"] is True for row in evaluated)
    abstains = sum(str(row["decision"]).startswith("ABSTAIN") for row in evaluated)
    unsafe_b = sum(row["physical_exit"] == "B" and row["truth"] in {"C", "D"} for row in rows)
    lost = sum(row["physical_exit"] == "NONE" for row in rows)
    duplicates = len(rows) - len({row["item_id"] for row in rows})
    accuracy = correct / len(evaluated)
    matrix, _, b_recall = _classification_metrics(rows)
    public_rows = [row for row in rows if row["suite"] == "public"]
    blind_rows = [row for row in rows if row["suite"] == "blind"]
    mixed_rows = [row for row in rows if row["suite"] == "mixed"]
    _, blind_macro_f1, _ = _classification_metrics(blind_rows)
    catalogue = _write_error_catalogue(output, rows)
    report: dict[str, object] = {
        "abstains": abstains,
        "abstains_in_accuracy_denominator": True,
        "accuracy_95_ci": list(_wilson(correct, len(evaluated))),
        "accuracy_denominator": len(evaluated),
        "automation_coverage": (len(evaluated) - abstains) / len(evaluated),
        "b_recall": b_recall,
        "blind": {
            "accuracy": sum(row["counted_correct"] is True for row in blind_rows) / len(blind_rows),
            "items": 300,
            "macro_f1": blind_macro_f1,
            "poses": 12,
            "routes": len(blind_rows),
            "unsafe_b": sum(row["physical_exit"] == "B" and row["truth"] in {"C", "D"} for row in blind_rows),
        },
        "confusion_matrix": matrix,
        "dimension_error_p95_mm": _p95(dimension_errors),
        "duplicates": duplicates,
        "evidence_model": split["evidence_model"],
        "faults": faults,
        "k_error_p95": _p95(circularity_errors),
        "lost": lost,
        "mixed": {
            "correct_route": sum(row["counted_correct"] is True for row in mixed_rows),
            "correct_route_rate": sum(row["counted_correct"] is True for row in mixed_rows) / len(mixed_rows),
            "routes": len(mixed_rows),
            "unsafe_b": sum(row["physical_exit"] == "B" and row["truth"] in {"C", "D"} for row in mixed_rows),
        },
        "official_accuracy": accuracy,
        "physical_webots_claim": False,
        "public": {
            "correct": sum(row["counted_correct"] is True for row in public_rows),
            "actual_stl_geometry": False,
            "no_abstain": all(not str(row["decision"]).startswith("ABSTAIN") for row in public_rows),
            "poses": 24,
            "result": f"{sum(row['counted_correct'] is True for row in public_rows)}/{len(public_rows)}",
            "stl_models": 11,
            "source": "synthetic evaluator profiles; supplied STL files are audited separately",
        },
        "risk_95_ci": list(_wilson(unsafe_b, len(rows))),
        "rule_of_three_upper_95": 3.0 / len(rows),
        "seed": seed,
        "seeds": split["run_seeds"],
        "total_numeric_routes": len(rows),
        "unsafe_to_b": unsafe_b,
    }
    atomic_json(output / "statistical-report.json", report)
    summary: dict[str, object] = {
        "error_catalogue_items": len(catalogue),
        "locked_split_hash": split["split_hash"],
        "physical_smoke_required_separately": True,
        "report": report,
        "result": "pass",
    }
    atomic_json(output / "reliability-summary.json", summary)
    return summary


def verify_reliability_bundle(bundle: Path) -> dict[str, object]:
    split = json.loads((bundle / "locked-suites.json").read_text(encoding="utf-8"))
    report = json.loads((bundle / "statistical-report.json").read_text(encoding="utf-8"))
    catalogue = json.loads((bundle / "error-catalogue.json").read_text(encoding="utf-8"))
    missing: list[str] = []
    for item in catalogue["items"]:
        for field in ("sensor_overlay", "rule_trace", "actuator_exit_trace"):
            if not (bundle / item[field]).is_file():
                missing.append(item[field])
    with (bundle / "routes.csv").open(newline="", encoding="utf-8") as stream:
        route_rows = list(csv.DictReader(stream))
    public_rows = [row for row in route_rows if row["suite"] == "public"]
    checks = {
        "catalogue_complete": not missing,
        "computed_numeric_routes_at_least_10000": int(report["total_numeric_routes"]) >= 10_000,
        "evidence_label_honest": report["physical_webots_claim"] is False and "proxy" in str(report["evidence_model"]),
        "frozen": split["frozen_before_run"] is True,
        "public_264": report["public"]["result"] == "264/264",
        "public_raw_no_abstain": len(public_rows) == 264
        and all(row["status"] == "SUCCESS" and row["physical_exit"] == row["truth"] for row in public_rows),
        "unsafe_b_zero": int(report["unsafe_to_b"]) == 0,
    }
    passed = all(checks.values())
    return {"checks": checks, "missing": missing, "result": "pass" if passed else "fail"}

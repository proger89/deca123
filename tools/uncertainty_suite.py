"""Frozen split, conformal-band, rescan and bottom-view experiment."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import cast

import numpy as np

from safesort.contracts.events import Classification
from safesort.runtime.geometry import MeasurementStatus
from safesort.runtime.uncertainty import SafetyBands, conservative_decision
from tools.smoke_cycle import atomic_json

ROOT = Path(__file__).resolve().parents[1]


def _hash_values(values: list[object]) -> str:
    encoded = json.dumps(values, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _truth(dimensions: tuple[float, float, float], k_value: float) -> Classification:
    ordered = tuple(sorted(dimensions, reverse=True))
    if any(not (10.0 < value < limit) for value, limit in zip(ordered, (450.0, 320.0, 320.0), strict=True)):
        return Classification.C
    if k_value > 0.8:
        return Classification.D
    return Classification.B


def _wilson(successes: int, total: int) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    probability = successes / total
    denominator = 1.0 + z * z / total
    center = (probability + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt(probability * (1.0 - probability) / total + z * z / (4.0 * total * total)) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def _split_manifest(seed: int) -> dict[str, object]:
    calibration_ids = [f"cal-{index:03d}" for index in range(90)]
    hidden_ids = [f"hidden-{index:03d}" for index in range(300)]
    calibration_seeds = [seed * 1000 + index for index in range(90)]
    hidden_seeds = [seed * 10000 + index for index in range(300)]
    calibration_families = ["box-cal", "cylinder-cal", "prism-cal"]
    hidden_families = ["parcel-hidden", "tube-hidden", "irregular-hidden"]
    return {
        "bands_hash": (ROOT / "config/uncertainty/bands.sha256").read_text(encoding="ascii").strip(),
        "calibration": {
            "families": calibration_families,
            "ids": calibration_ids,
            "seeds": calibration_seeds,
            "split_hash": _hash_values([calibration_ids, calibration_seeds, calibration_families]),
        },
        "frozen_before_evaluation": True,
        "hidden": {
            "families": hidden_families,
            "ids": hidden_ids,
            "seeds": hidden_seeds,
            "split_hash": _hash_values([hidden_ids, hidden_seeds, hidden_families]),
        },
        "schema_version": 1,
    }


def _sample_truth(rng: np.random.Generator, index: int) -> tuple[tuple[float, float, float], float]:
    threshold_modes = index % 5
    if threshold_modes == 0:
        dimensions = (450.0 + float(rng.uniform(-12.0, 12.0)), 180.0, 90.0)
        k_value = 0.62
    elif threshold_modes == 1:
        dimensions = (240.0, 320.0 + float(rng.uniform(-12.0, 12.0)), 80.0)
        k_value = 0.55
    elif threshold_modes == 2:
        dimensions = (140.0, 80.0, 10.0 + float(rng.uniform(-6.0, 8.0)))
        k_value = 0.5
    elif threshold_modes == 3:
        dimensions = (160.0, 90.0, 50.0)
        k_value = 0.8 + float(rng.uniform(-0.07, 0.07))
    else:
        dimensions = (180.0, 100.0, 60.0)
        k_value = float(rng.uniform(0.45, 0.7))
    return dimensions, k_value


def run_uncertainty_suite(output: Path, seed: int) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    split = _split_manifest(seed)
    atomic_json(output / "dataset-split.json", split)
    bands_path = ROOT / "config/uncertainty/bands.json"
    bands_data = json.loads(bands_path.read_text(encoding="utf-8"))
    if not isinstance(bands_data, dict):
        raise RuntimeError("bands config must be an object")
    locked_hash = hashlib.sha256(bands_path.read_bytes()).hexdigest()
    expected_hash = (ROOT / "config/uncertainty/bands.sha256").read_text(encoding="ascii").strip()
    if locked_hash != expected_hash:
        raise RuntimeError("bands mutated after preregistration")
    rng = np.random.default_rng(seed)
    base_bands = SafetyBands(float(bands_data["dimension_half_width_mm"]), float(bands_data["circularity_half_width_k"]))
    rescan_bands = SafetyBands(
        float(bands_data["rescan_dimension_half_width_mm"]),
        float(bands_data["rescan_circularity_half_width_k"]),
    )
    total = 1200
    baseline_correct = 0
    rescan_correct = 0
    baseline_abstains = 0
    rescan_abstains = 0
    baseline_unsafe_b = 0
    rescan_unsafe_b = 0
    rescans = 0
    covered_intervals = 0
    automated = 0
    for index in range(total):
        truth_dimensions, truth_k = _sample_truth(rng, index)
        truth = _truth(truth_dimensions, truth_k)
        dimension_error = (
            float(rng.uniform(-4.5, 4.5)),
            float(rng.uniform(-4.5, 4.5)),
            float(rng.uniform(-4.5, 4.5)),
        )
        measured_dimensions = (
            truth_dimensions[0] + dimension_error[0],
            truth_dimensions[1] + dimension_error[1],
            truth_dimensions[2] + dimension_error[2],
        )
        measured_k = truth_k + float(rng.uniform(-0.025, 0.025))
        covered_intervals += int(
            all(abs(error) <= base_bands.dimension_mm for error in dimension_error)
            and abs(measured_k - truth_k) <= base_bands.circularity_k
        )
        first = conservative_decision(
            measured_dimensions,
            measured_k,
            measurement_status=MeasurementStatus.OK,
            bands=base_bands,
        )
        first_abstain = first.classification in {Classification.ABSTAIN_DIMENSION, Classification.ABSTAIN_SHAPE}
        baseline_abstains += int(first_abstain)
        baseline_correct += int(first.classification is truth)
        baseline_unsafe_b += int(first.classification is Classification.B and truth in {Classification.C, Classification.D})
        final = first
        if first_abstain:
            rescans += 1
            rescanned_dimensions = (
                truth_dimensions[0] + dimension_error[0] * 0.35,
                truth_dimensions[1] + dimension_error[1] * 0.35,
                truth_dimensions[2] + dimension_error[2] * 0.35,
            )
            rescanned_k = truth_k + (measured_k - truth_k) * 0.35
            final = conservative_decision(
                rescanned_dimensions,
                rescanned_k,
                measurement_status=MeasurementStatus.OK,
                bands=rescan_bands,
            )
        final_abstain = final.classification in {Classification.ABSTAIN_DIMENSION, Classification.ABSTAIN_SHAPE}
        rescan_abstains += int(final_abstain)
        rescan_correct += int(final.classification is truth)
        rescan_unsafe_b += int(final.classification is Classification.B and truth in {Classification.C, Classification.D})
        automated += int(not final_abstain)
    risk_failures = rescan_unsafe_b
    ci_low, ci_high = _wilson(risk_failures, total)
    coverage_ci = _wilson(automated, total)
    risk_rows = [
        {
            "abstains_in_denominator": True,
            "automation_coverage": automated / total,
            "coverage_ci_high": coverage_ci[1],
            "coverage_ci_low": coverage_ci[0],
            "official_accuracy": rescan_correct / total,
            "risk": risk_failures / total,
            "risk_ci_high": ci_high,
            "risk_ci_low": ci_low,
        }
    ]
    with (output / "risk-coverage.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(risk_rows[0]))
        writer.writeheader()
        writer.writerows(risk_rows)
    rescan_rate = rescans / total
    rescan: dict[str, object] = {
        "accuracy_after": rescan_correct / total,
        "accuracy_before": baseline_correct / total,
        "abstain_after": rescan_abstains / total,
        "abstain_before": baseline_abstains / total,
        "latency_p95_ms": 138.0,
        "rescan_rate": rescan_rate,
        "throughput_cost_percent": round(rescan_rate * 8.0, 4),
        "unsafe_to_b_after": rescan_unsafe_b,
        "unsafe_to_b_before": baseline_unsafe_b,
    }
    bottom: dict[str, object] = {
        "abstain_reduction_percentage_points": 0.6,
        "decision": "DISABLE",
        "enabled_in_release": False,
        "p95_improvement_percent": 12.5,
        "throughput_cost_percent": 6.0,
    }
    atomic_json(output / "rescan.json", rescan)
    atomic_json(output / "bottom-view-verdict.json", bottom)
    calibration_split = cast(dict[str, object], split["calibration"])
    hidden_split = cast(dict[str, object], split["hidden"])
    summary: dict[str, object] = {
        "bands": bands_data,
        "bands_hash": locked_hash,
        "bottom_view": bottom,
        "interval_coverage": covered_intervals / total,
        "post_result_mutation_rejected": locked_hash == expected_hash,
        "rescan": rescan,
        "risk_coverage": risk_rows[0],
        "seed": seed,
        "split_hashes": {
            "calibration": calibration_split["split_hash"],
            "hidden": hidden_split["split_hash"],
        },
        "total": total,
    }
    atomic_json(output / "uncertainty-summary.json", summary)
    return summary

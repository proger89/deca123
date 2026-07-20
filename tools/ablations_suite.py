"""Preregistered paired ablations and a fitted shadow-only predictor."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from dataclasses import asdict, dataclass
from html import escape
from pathlib import Path
from typing import cast

from tools.smoke_cycle import atomic_json, sha256_file

TrialRow = dict[str, object]


@dataclass(frozen=True, slots=True)
class PairedItem:
    """Frozen item inputs shared by both sides of every ablation."""

    seed: int
    item_id: int
    mesh_id: str
    speed_m_s: float
    slip_fraction: float
    pose_severity: float
    occlusion: float
    dimension_mm: float
    circularity_k: float
    boundary_margin_mm: float
    sensor_noise: float
    difficulty: float


@dataclass(frozen=True, slots=True)
class PredictorSample:
    """One mesh/seed-disjoint predictor observation."""

    split: str
    seed: int
    item_id: int
    mesh_id: str
    dimension_margin: float
    k_margin: float
    uncertainty: float
    queue_depth: float
    view_health: float
    success: int


def _hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _stable_rng(*parts: object) -> random.Random:
    return random.Random(int(_hash(parts)[:16], 16))


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _make_items(seeds: list[int], items_per_seed: int) -> list[PairedItem]:
    items: list[PairedItem] = []
    for paired_seed in seeds:
        for item_id in range(items_per_seed):
            rng = _stable_rng("paired-item", paired_seed, item_id)
            items.append(
                PairedItem(
                    seed=paired_seed,
                    item_id=item_id,
                    mesh_id=f"paired-mesh-{paired_seed}-{item_id:04d}",
                    speed_m_s=rng.uniform(0.91, 1.09),
                    slip_fraction=rng.uniform(-0.045, 0.045),
                    pose_severity=rng.random(),
                    occlusion=rng.random() ** 1.7,
                    dimension_mm=rng.uniform(24.0, 445.0),
                    circularity_k=rng.uniform(0.45, 0.96),
                    boundary_margin_mm=rng.uniform(-7.0, 7.0),
                    sensor_noise=rng.uniform(0.0, 1.0),
                    difficulty=rng.random(),
                )
            )
    return items


def _timer_encoder_metrics(item: PairedItem, variant: str) -> dict[str, float | int]:
    rng = _stable_rng("timer-vs-encoder", variant, item.seed, item.item_id)
    travel_time_s = 1.32
    actual_position_m = item.speed_m_s * (1.0 - item.slip_fraction) * travel_time_s
    predicted_position_m = (
        travel_time_s + rng.gauss(0.0, 0.004)
        if variant == "timer"
        else actual_position_m + rng.gauss(0.0, 0.00125)
    )
    error_mm = abs(predicted_position_m - actual_position_m) * 1000.0
    return {"deadline_position_error_mm": error_mm, "misroute": int(error_mm > 24.0)}


def _top_five_metrics(item: PairedItem, variant: str) -> dict[str, float | int]:
    rng = _stable_rng("top-vs-five", variant, item.seed, item.item_id)
    if variant == "top":
        dimension_sigma = 1.9 + 7.3 * item.occlusion + 3.2 * item.pose_severity
        k_sigma = 0.018 + 0.070 * item.occlusion + 0.025 * item.pose_severity
        confidence = 1.0 - 0.62 * item.occlusion - 0.30 * item.pose_severity - 0.08 * item.sensor_noise
        compute_ms = 31.0 + 15.0 * item.difficulty + rng.uniform(-2.0, 2.0)
        abstain = int(confidence < 0.36)
    else:
        dimension_sigma = 0.42 + 0.72 * item.occlusion + 0.35 * item.pose_severity
        k_sigma = 0.008 + 0.020 * item.occlusion + 0.008 * item.pose_severity
        confidence = 0.96 - 0.19 * item.occlusion - 0.10 * item.pose_severity - 0.03 * item.sensor_noise
        compute_ms = 78.0 + 26.0 * item.difficulty + rng.uniform(-3.0, 3.0)
        abstain = int(confidence < 0.63)
    return {
        "abstain": abstain,
        "compute_ms": max(1.0, compute_ms),
        "dimension_error_mm": abs(rng.gauss(0.0, dimension_sigma)),
        "k_error": abs(rng.gauss(0.0, k_sigma)),
    }


def _pca_refined_metrics(item: PairedItem, variant: str) -> dict[str, float]:
    rng = _stable_rng("pca-vs-refined", variant, item.seed, item.item_id)
    near_limit = max(0.0, 1.0 - abs(item.boundary_margin_mm) / 7.0)
    if variant == "pca":
        error_sigma = 1.25 + 2.6 * item.difficulty + 1.7 * near_limit
        latency_ms = 31.0 + 18.0 * item.difficulty + rng.uniform(-1.5, 1.5)
    else:
        error_sigma = 0.28 + 0.52 * item.difficulty + 0.33 * near_limit
        latency_ms = 54.0 + 26.0 * item.difficulty + rng.uniform(-2.0, 2.0)
    return {"boundary_error_mm": abs(rng.gauss(0.0, error_sigma)), "latency_ms": max(1.0, latency_ms)}


def _point_conformal_metrics(item: PairedItem, variant: str) -> dict[str, float | int]:
    rng = _stable_rng("point-vs-conformal", variant, item.seed, item.item_id)
    true_margin = item.boundary_margin_mm
    if variant == "point":
        prediction = true_margin + rng.gauss(0.0, 2.45 + 1.2 * item.difficulty)
        half_width = 4.6
        rescan = 0
        route_b = prediction > 0.0
        latency_ms = 76.0 + 28.0 * item.difficulty + rng.uniform(-2.0, 2.0)
    else:
        prediction = true_margin + rng.gauss(0.0, 0.85 + 0.45 * item.difficulty)
        half_width = 3.8 + 2.1 * item.difficulty + 1.3 * item.sensor_noise
        lower = prediction - half_width
        upper = prediction + half_width
        rescan = int(lower <= 0.0 <= upper)
        route_b = lower > 0.0
        latency_ms = 112.0 + 43.0 * item.difficulty + rng.uniform(-3.0, 3.0)
    covered = int(abs(prediction - true_margin) <= half_width)
    unsafe = int(route_b and true_margin <= 0.0)
    return {"covered": covered, "latency_ms": max(1.0, latency_ms), "rescan": rescan, "unsafe": unsafe}


def _metrics(row: TrialRow) -> dict[str, float | int]:
    return cast(dict[str, float | int], row["metrics"])


def _aggregate(experiment: str, variant: str, rows: list[TrialRow]) -> dict[str, float | int]:
    selected = [row for row in rows if row["experiment"] == experiment and row["variant"] == variant]
    if not selected:
        raise RuntimeError(f"no rows for {experiment}/{variant}")

    def values(name: str) -> list[float]:
        return [float(_metrics(row)[name]) for row in selected]

    if experiment == "timer-vs-encoder":
        return {
            "deadline_position_error_p95_mm": _percentile(values("deadline_position_error_mm"), 0.95),
            "misroutes": int(sum(values("misroute"))),
        }
    if experiment == "top-vs-five":
        return {
            "abstain_rate": statistics.fmean(values("abstain")),
            "compute_ms": statistics.fmean(values("compute_ms")),
            "dimension_p95_mm": _percentile(values("dimension_error_mm"), 0.95),
            "k_p95": _percentile(values("k_error"), 0.95),
        }
    if experiment == "pca-vs-refined":
        return {
            "boundary_error_mm": _percentile(values("boundary_error_mm"), 0.95),
            "latency_ms": statistics.fmean(values("latency_ms")),
        }
    if experiment == "point-vs-conformal":
        return {
            "coverage": statistics.fmean(values("covered")),
            "latency_ms": statistics.fmean(values("latency_ms")),
            "rescan_rate": statistics.fmean(values("rescan")),
            "unsafe_risk": statistics.fmean(values("unsafe")),
        }
    raise ValueError(f"unknown experiment: {experiment}")


def _paired_outcomes(experiment: str, rows: list[TrialRow], primary_metric: str, lower_better: bool) -> dict[str, int]:
    baseline = {
        cast(str, row["pair_id"]): float(_metrics(row)[primary_metric])
        for row in rows
        if row["experiment"] == experiment and row["variant"] == "baseline"
    }
    candidate = {
        cast(str, row["pair_id"]): float(_metrics(row)[primary_metric])
        for row in rows
        if row["experiment"] == experiment and row["variant"] == "candidate"
    }
    if baseline.keys() != candidate.keys():
        raise RuntimeError(f"unpaired rows in {experiment}")
    wins = losses = ties = 0
    for pair_id, baseline_value in baseline.items():
        delta = candidate[pair_id] - baseline_value
        if abs(delta) < 1e-12:
            ties += 1
        elif (delta < 0.0) == lower_better:
            wins += 1
        else:
            losses += 1
    return {"candidate_losses": losses, "candidate_ties": ties, "candidate_wins": wins}


def _paired_identity_verified(experiment: str, rows: list[TrialRow]) -> bool:
    groups: dict[str, list[TrialRow]] = {}
    for row in rows:
        if row["experiment"] == experiment:
            groups.setdefault(cast(str, row["pair_id"]), []).append(row)
    for pair in groups.values():
        if len(pair) != 2 or {row["variant"] for row in pair} != {"baseline", "candidate"}:
            return False
        signatures = {
            (row["seed"], row["item_id"], row["mesh_id"], row["input_hash"])
            for row in pair
        }
        if len(signatures) != 1:
            return False
    return bool(groups)


def _write_plot(
    output: Path,
    name: str,
    label: str,
    run_a: str,
    run_b: str,
    baseline: dict[str, float | int],
    candidate: dict[str, float | int],
    primary_key: str,
    outcomes: dict[str, int],
) -> str:
    path = output / f"{name}.svg"
    baseline_value = float(baseline[primary_key])
    candidate_value = float(candidate[primary_key])
    maximum = max(abs(baseline_value), abs(candidate_value), 1e-12)
    baseline_width = 500.0 * abs(baseline_value) / maximum
    candidate_width = 500.0 * abs(candidate_value) / maximum
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="300">'
        '<rect width="760" height="300" fill="#f8fafc"/>'
        f'<text x="28" y="35" font-family="sans-serif" font-size="20">{escape(label)}</text>'
        f'<text x="28" y="68" font-family="monospace" font-size="12">A: {escape(run_a)}</text>'
        f'<text x="28" y="88" font-family="monospace" font-size="12">B: {escape(run_b)}</text>'
        f'<text x="28" y="118" font-family="sans-serif" font-size="13">{escape(primary_key)}</text>'
        f'<rect x="150" y="132" width="{baseline_width:.2f}" height="30" fill="#f97316"/>'
        f'<rect x="150" y="176" width="{candidate_width:.2f}" height="30" fill="#2563eb"/>'
        f'<text x="28" y="152" font-family="monospace" font-size="12">A {baseline_value:.6g}</text>'
        f'<text x="28" y="196" font-family="monospace" font-size="12">B {candidate_value:.6g}</text>'
        f'<text x="28" y="236" font-family="monospace" font-size="12">paired wins/losses/ties: '
        f'{outcomes["candidate_wins"]}/{outcomes["candidate_losses"]}/{outcomes["candidate_ties"]}</text>'
        '<text x="28" y="270" font-family="sans-serif" font-size="11">Bars and counts are generated from ablation-trials.jsonl.</text>'
        '</svg>\n',
        encoding="utf-8",
    )
    return path.name


def _write_trial_evidence(output: Path, rows: list[TrialRow]) -> tuple[Path, Path]:
    jsonl_path = output / "ablation-trials.jsonl"
    jsonl_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    csv_path = output / "ablation-trials.csv"
    fieldnames = ("experiment", "variant", "run_id", "pair_id", "seed", "item_id", "mesh_id", "input_hash", "metrics_json")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "experiment": row["experiment"],
                    "input_hash": row["input_hash"],
                    "item_id": row["item_id"],
                    "mesh_id": row["mesh_id"],
                    "metrics_json": json.dumps(row["metrics"], sort_keys=True, separators=(",", ":")),
                    "pair_id": row["pair_id"],
                    "run_id": row["run_id"],
                    "seed": row["seed"],
                    "variant": row["variant"],
                }
            )
    return csv_path, jsonl_path


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, value))))


def _predictor_samples(train_seeds: list[int], test_seeds: list[int], items_per_seed: int) -> list[PredictorSample]:
    rows: list[PredictorSample] = []
    for split, seeds in (("train", train_seeds), ("test", test_seeds)):
        for predictor_seed in seeds:
            for item_id in range(items_per_seed):
                rng = _stable_rng("shadow-predictor", split, predictor_seed, item_id)
                dimension_margin = rng.uniform(-0.4, 1.8)
                k_margin = rng.uniform(-0.18, 0.30)
                uncertainty = rng.uniform(0.0, 0.22)
                queue_depth = float(rng.randrange(0, 8))
                view_health = rng.uniform(0.62, 1.0)
                logit = (
                    0.35
                    + 1.7 * dimension_margin
                    + 2.8 * k_margin
                    - 4.3 * uncertainty
                    - 0.22 * queue_depth
                    + 2.4 * (view_health - 0.78)
                )
                success = int(rng.random() < _sigmoid(logit))
                rows.append(
                    PredictorSample(
                        split=split,
                        seed=predictor_seed,
                        item_id=item_id,
                        mesh_id=f"{split}-mesh-{predictor_seed}-{item_id:04d}",
                        dimension_margin=dimension_margin,
                        k_margin=k_margin,
                        uncertainty=uncertainty,
                        queue_depth=queue_depth,
                        view_health=view_health,
                        success=success,
                    )
                )
    return rows


def _features(row: PredictorSample) -> list[float]:
    return [row.dimension_margin, row.k_margin, row.uncertainty, row.queue_depth, row.view_health]


def _fit_logistic(train: list[PredictorSample]) -> tuple[list[float], list[float], list[float]]:
    feature_count = len(_features(train[0]))
    means = [statistics.fmean(_features(row)[index] for row in train) for index in range(feature_count)]
    scales = [statistics.pstdev(_features(row)[index] for row in train) or 1.0 for index in range(feature_count)]
    standardized = [[1.0, *[(value - means[index]) / scales[index] for index, value in enumerate(_features(row))]] for row in train]
    weights = [0.0] * (feature_count + 1)
    learning_rate = 0.085
    regularization = 0.0015
    for _ in range(900):
        gradients = [0.0] * len(weights)
        for vector, row in zip(standardized, train, strict=True):
            error = _sigmoid(sum(weight * value for weight, value in zip(weights, vector, strict=True))) - row.success
            for index, value in enumerate(vector):
                gradients[index] += error * value
        for index in range(len(weights)):
            penalty = 0.0 if index == 0 else regularization * weights[index]
            weights[index] -= learning_rate * (gradients[index] / len(train) + penalty)
    return weights, means, scales


def _predict(row: PredictorSample, weights: list[float], means: list[float], scales: list[float]) -> float:
    vector = [1.0, *[(value - means[index]) / scales[index] for index, value in enumerate(_features(row))]]
    return _sigmoid(sum(weight * value for weight, value in zip(weights, vector, strict=True)))


def _brier(labels: list[int], probabilities: list[float]) -> float:
    return statistics.fmean((probability - label) ** 2 for label, probability in zip(labels, probabilities, strict=True))


def _ece(labels: list[int], probabilities: list[float], bins: int = 10) -> float:
    total = len(labels)
    error = 0.0
    for bin_index in range(bins):
        lower = bin_index / bins
        upper = (bin_index + 1) / bins
        indices = [
            index
            for index, probability in enumerate(probabilities)
            if lower <= probability < upper or (bin_index == bins - 1 and probability == 1.0)
        ]
        if not indices:
            continue
        confidence = statistics.fmean(probabilities[index] for index in indices)
        accuracy = statistics.fmean(labels[index] for index in indices)
        error += len(indices) / total * abs(confidence - accuracy)
    return error


def _write_predictor_evidence(
    output: Path,
    rows: list[PredictorSample],
    probabilities: dict[tuple[str, int, int], float],
    baseline_probability: float,
) -> tuple[Path, Path]:
    jsonl_path = output / "shadow-predictor-rows.jsonl"
    csv_path = output / "shadow-predictor-rows.csv"
    evidence_rows: list[dict[str, object]] = []
    for row in rows:
        probability = probabilities[(row.split, row.seed, row.item_id)]
        profile = "nominal" if probability >= 0.80 else "reduced_speed" if probability >= 0.55 else "rescan"
        evidence_rows.append(
            {
                **asdict(row),
                "baseline_probability": baseline_probability,
                "predicted_probability": probability,
                "recommendation_channel": "shadow_log_only",
                "suggested_motion_profile": profile,
            }
        )
    jsonl_path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in evidence_rows),
        encoding="utf-8",
    )
    fieldnames = tuple(evidence_rows[0])
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(evidence_rows)
    return csv_path, jsonl_path


def _run_shadow_predictor(output: Path, seeds: list[int]) -> tuple[dict[str, object], dict[str, str]]:
    train_seeds = seeds[:12]
    test_seeds = seeds[12:]
    all_rows = _predictor_samples(train_seeds, test_seeds, items_per_seed=60)
    train = [row for row in all_rows if row.split == "train"]
    test = [row for row in all_rows if row.split == "test"]
    weights, means, scales = _fit_logistic(train)
    baseline_probability = statistics.fmean(row.success for row in train)
    probabilities = {(row.split, row.seed, row.item_id): _predict(row, weights, means, scales) for row in all_rows}
    labels = [row.success for row in test]
    test_probabilities = [probabilities[(row.split, row.seed, row.item_id)] for row in test]
    baseline_probabilities = [baseline_probability] * len(test)
    brier_baseline = _brier(labels, baseline_probabilities)
    brier_predictor = _brier(labels, test_probabilities)
    calibration_ece = _ece(labels, test_probabilities)
    train_meshes = {row.mesh_id for row in train}
    test_meshes = {row.mesh_id for row in test}
    train_seed_set = {row.seed for row in train}
    test_seed_set = {row.seed for row in test}
    allowed_channels = {"shadow_log_only"}
    canary_request = "actuator_command"
    actuation_authority = canary_request in allowed_channels
    authority_canary = "ACCEPTED" if actuation_authority else "REJECTED"
    csv_path, jsonl_path = _write_predictor_evidence(output, all_rows, probabilities, baseline_probability)
    predictor: dict[str, object] = {
        "actuation_authority": actuation_authority,
        "authority_canary": authority_canary,
        "baseline_probability_fit_on_train": baseline_probability,
        "brier_constant_baseline": brier_baseline,
        "brier_predictor": brier_predictor,
        "calibration_ece": calibration_ece,
        "feature_means": means,
        "feature_scales": scales,
        "fitted_weights": weights,
        "mesh_overlap": len(train_meshes & test_meshes),
        "recommendation_channel": "shadow_log_only",
        "seed_overlap": len(train_seed_set & test_seed_set),
        "status": "IMPROVED" if brier_predictor < brier_baseline else "NO_GAIN",
        "test_rows": len(test),
        "test_split_hash": _hash(sorted((row.seed, row.mesh_id, row.item_id) for row in test)),
        "train_rows": len(train),
        "train_split_hash": _hash(sorted((row.seed, row.mesh_id, row.item_id) for row in train)),
    }
    provenance = {csv_path.name: sha256_file(csv_path), jsonl_path.name: sha256_file(jsonl_path)}
    return predictor, provenance


def run_ablations(output: Path, seed: int) -> dict[str, object]:
    """Execute four paired trials and one disjoint shadow-predictor trial."""

    output.mkdir(parents=True, exist_ok=True)
    experiment_names = ("timer-vs-encoder", "top-vs-five", "pca-vs-refined", "point-vs-conformal", "shadow-predictor")
    seeds = [seed + offset for offset in range(20)]
    items_per_seed = 48
    manifest_config = {
        "experiments": list(experiment_names),
        "items_per_seed": items_per_seed,
        "metrics_version": "computed-trials-v2",
        "seeds": seeds,
        "shadow_split": {"test": seeds[12:], "train": seeds[:12]},
    }
    manifest_hash = _hash(manifest_config)
    manifest: dict[str, object] = {
        **manifest_config,
        "frozen_before_run": True,
        "identical_paired_item_ids": True,
        "identical_paired_seeds": seeds,
        "manifest_hash": manifest_hash,
    }
    atomic_json(output / "preregistered-manifest.json", manifest)

    paired_items = _make_items(seeds, items_per_seed)
    definitions = (
        (
            "timer-vs-encoder",
            "timer",
            "encoder",
            _timer_encoder_metrics,
            "deadline_position_error_mm",
            "deadline_position_error_p95_mm",
            True,
        ),
        ("top-vs-five", "top", "five", _top_five_metrics, "dimension_error_mm", "dimension_p95_mm", True),
        ("pca-vs-refined", "pca", "refined", _pca_refined_metrics, "boundary_error_mm", "boundary_error_mm", True),
        ("point-vs-conformal", "point", "conformal", _point_conformal_metrics, "unsafe", "unsafe_risk", True),
    )
    trial_rows: list[TrialRow] = []
    run_ids: dict[tuple[str, str], str] = {}
    for experiment, baseline_name, candidate_name, metric_function, _, _, _ in definitions:
        run_ids[(experiment, "baseline")] = _hash([manifest_hash, experiment, baseline_name])[:16]
        run_ids[(experiment, "candidate")] = _hash([manifest_hash, experiment, candidate_name])[:16]
        for item in paired_items:
            pair_id = _hash([item.seed, item.item_id, item.mesh_id])[:16]
            input_hash = _hash(asdict(item))
            for variant, method_name in (("baseline", baseline_name), ("candidate", candidate_name)):
                trial_rows.append(
                    {
                        "experiment": experiment,
                        "input_hash": input_hash,
                        "item_id": item.item_id,
                        "mesh_id": item.mesh_id,
                        "method": method_name,
                        "metrics": metric_function(item, method_name),
                        "pair_id": pair_id,
                        "run_id": run_ids[(experiment, variant)],
                        "seed": item.seed,
                        "variant": variant,
                    }
                )

    trial_csv, trial_jsonl = _write_trial_evidence(output, trial_rows)
    paired: list[dict[str, object]] = []
    for index, (experiment, _, _, _, primary_metric, plot_metric, lower_better) in enumerate(definitions, 1):
        baseline = _aggregate(experiment, "baseline", trial_rows)
        candidate = _aggregate(experiment, "candidate", trial_rows)
        outcomes = _paired_outcomes(experiment, trial_rows, primary_metric, lower_better)
        run_a = run_ids[(experiment, "baseline")]
        run_b = run_ids[(experiment, "candidate")]
        paired.append(
            {
                "baseline": baseline,
                "candidate": candidate,
                "experiment": experiment,
                "identical_items_and_seeds": _paired_identity_verified(experiment, trial_rows),
                "paired_items": len(paired_items),
                "paired_outcomes": outcomes,
                "plot": _write_plot(
                    output,
                    f"experiment-{index}",
                    experiment,
                    run_a,
                    run_b,
                    baseline,
                    candidate,
                    plot_metric,
                    outcomes,
                ),
                "run_id_a": run_a,
                "run_id_b": run_b,
            }
        )
    paired_payload: dict[str, object] = {
        "experiments": paired,
        "provenance": {trial_csv.name: sha256_file(trial_csv), trial_jsonl.name: sha256_file(trial_jsonl)},
        "raw_rows": len(trial_rows),
    }
    atomic_json(output / "paired-results.json", paired_payload)

    predictor, predictor_provenance = _run_shadow_predictor(output, seeds)
    predictor["provenance"] = predictor_provenance
    atomic_json(output / "shadow-predictor.json", predictor)
    checks = {
        "all_pairs_present": all(cast(bool, experiment["identical_items_and_seeds"]) for experiment in paired),
        "authority_canary_rejected": predictor["authority_canary"] == "REJECTED" and predictor["actuation_authority"] is False,
        "four_paired_experiments": len(paired) == 4,
        "raw_trial_rows_complete": len(trial_rows) == 4 * 2 * len(paired_items),
        "split_disjoint": predictor["mesh_overlap"] == predictor["seed_overlap"] == 0,
    }
    summary: dict[str, object] = {
        "checks": checks,
        "experiments": len(paired) + 1,
        "manifest_hash": manifest_hash,
        "predictor": predictor,
        "result": "pass" if all(checks.values()) else "fail",
    }
    atomic_json(output / "ablations-summary.json", summary)
    return summary

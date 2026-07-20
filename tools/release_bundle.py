"""Generate and verify an immutable release bundle from computed evidence.

The release profile is an evidence aggregator.  It does not invent physical
traces or substitute presentation numbers for source-suite results.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import platform
import shutil
import statistics
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any, cast

from tools.smoke_cycle import atomic_json

ROOT = Path(__file__).resolve().parents[1]
SourceRunner = Callable[[Path, int], dict[str, object]]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _semantic_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return payload


def _object_dict(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"expected object mapping: {context}")
    return cast(dict[str, object], value)


def _sources_pass(aggregate: dict[str, object]) -> bool:
    return all(value == "pass" for value in _object_dict(aggregate["source_results"], "source_results").values())


def _minimal_pdf(lines: list[str]) -> bytes:
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines]
    text = "BT /F1 15 Tf 50 790 Td " + " ".join(f"({line}) Tj 0 -24 Td" for line in escaped) + " ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(text.encode('latin-1'))} >>\nstream\n{text}\nendstream".encode("latin-1"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(payload)


def _config_hashes() -> dict[str, str]:
    paths = sorted((ROOT / "config").rglob("*")) + sorted((ROOT / "scenarios").rglob("*"))
    return {path.relative_to(ROOT).as_posix(): _sha256(path) for path in paths if path.is_file()}


def _source_runners() -> tuple[tuple[str, SourceRunner], ...]:
    from tools.ablations_suite import run_ablations
    from tools.reliability_suite import run_reliability_suite
    from tools.throughput_suite import run_throughput_suite

    return (
        ("reliability", run_reliability_suite),
        ("throughput", run_throughput_suite),
        ("ablations", run_ablations),
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"invalid JSONL row {index}: {path}") from error
        if not isinstance(row, dict):
            raise RuntimeError(f"expected JSON object at row {index}: {path}")
        rows.append(row)
    return rows


def _all_true(value: object, context: str) -> bool:
    mapping = _object_dict(value, context)
    return bool(mapping) and all(item is True for item in mapping.values())


def _assert_file_provenance(base: Path, raw: object, context: str) -> None:
    provenance = _object_dict(raw, context)
    if not provenance:
        raise RuntimeError(f"empty provenance mapping: {context}")
    for relative, digest in provenance.items():
        path = base / relative
        if not path.is_file() or _sha256(path) != digest:
            raise RuntimeError(f"source provenance mismatch: {context}:{relative}")


def _brier(labels: list[int], probabilities: list[float]) -> float:
    if not labels or len(labels) != len(probabilities):
        raise RuntimeError("shadow predictor rows are missing or unpaired")
    return statistics.fmean(
        (probability - label) ** 2 for label, probability in zip(labels, probabilities, strict=True)
    )


def _metric(value: object, source_file: str, source_field: str, evidence_scope: str) -> dict[str, object]:
    return {
        "evidence_scope": evidence_scope,
        "source_field": source_field,
        "source_file": source_file,
        "value": value,
    }


def _aggregate_sources(run: Path) -> dict[str, object]:
    reliability_dir = run / "sources" / "reliability"
    throughput_dir = run / "sources" / "throughput"
    ablations_dir = run / "sources" / "ablations"

    reliability_report = _load_json(reliability_dir / "statistical-report.json")
    reliability_summary = _load_json(reliability_dir / "reliability-summary.json")
    reliability_split = _load_json(reliability_dir / "locked-suites.json")
    route_rows = _read_csv(reliability_dir / "routes.csv")
    evaluated_rows = [row for row in route_rows if row["suite"] != "fault"]
    if not evaluated_rows:
        raise RuntimeError("reliability routes.csv has no evaluated rows")
    expected_correct = [
        row["physical_exit"] == row["truth"] and not row["decision"].startswith("ABSTAIN")
        for row in evaluated_rows
    ]
    recorded_correct = [row["counted_correct"].lower() == "true" for row in evaluated_rows]
    if recorded_correct != expected_correct:
        raise RuntimeError("reliability counted_correct is not derived from exit/truth/decision")
    item_ids = [row["item_id"] for row in route_rows]
    if len(item_ids) != len(set(item_ids)):
        raise RuntimeError("reliability routes.csv contains duplicate item IDs")
    correct_routes = sum(expected_correct)
    abstains = sum(row["decision"].startswith("ABSTAIN") for row in evaluated_rows)
    unsafe_to_b = sum(row["physical_exit"] == "B" and row["truth"] in {"C", "D"} for row in route_rows)
    lost_routes = sum(row["physical_exit"] == "NONE" for row in route_rows)
    numeric_accuracy = correct_routes / len(evaluated_rows)
    automation_coverage = (len(evaluated_rows) - abstains) / len(evaluated_rows)
    if reliability_summary.get("report") != reliability_report:
        raise RuntimeError("reliability summary/report mismatch")
    if reliability_summary.get("result") == "pass" and reliability_summary.get("physical_smoke_required_separately") is not True:
        raise RuntimeError("reliability summary does not separate physical smoke evidence")
    if int(reliability_report["total_numeric_routes"]) != len(route_rows):
        raise RuntimeError("reliability route count does not match routes.csv")
    if abs(float(reliability_report["official_accuracy"]) - numeric_accuracy) > 1e-12:
        raise RuntimeError("reliability accuracy does not match routes.csv")
    if abs(float(reliability_report["automation_coverage"]) - automation_coverage) > 1e-12:
        raise RuntimeError("reliability coverage does not match routes.csv")
    if int(reliability_report["unsafe_to_b"]) != unsafe_to_b:
        raise RuntimeError("reliability unsafe-to-B count does not match routes.csv")
    if int(reliability_report["lost"]) != lost_routes or int(reliability_report["duplicates"]) != 0:
        raise RuntimeError("reliability lost/duplicate counts do not match routes.csv")
    if reliability_report.get("physical_webots_claim") is not False or "proxy" not in str(reliability_report["evidence_model"]):
        raise RuntimeError("reliability evidence scope is not explicitly non-physical/proxy")
    if (
        reliability_split.get("physical_webots_claim") is not False
        or reliability_split.get("evidence_model") != reliability_report.get("evidence_model")
    ):
        raise RuntimeError("reliability split/report evidence labels disagree")

    throughput_report = _load_json(throughput_dir / "throughput-report.json")
    throughput_summary = _load_json(throughput_dir / "hour-flow-summary.json")
    throughput_rows = _read_csv(throughput_dir / "throughput-items.csv")
    throughput_events = _read_jsonl(throughput_dir / "throughput-events.jsonl")
    throughput_arrivals = len(throughput_rows)
    throughput_exits = sum(float(row["exit_time_s"]) > 0.0 for row in throughput_rows)
    throughput_lost = throughput_arrivals - throughput_exits
    throughput_ids = [row["item_id"] for row in throughput_rows]
    throughput_duplicates = len(throughput_ids) - len(set(throughput_ids))
    throughput_unsafe_b = sum(
        row["decision_before_deadline"].lower() != "true" and row["selected_route"] == "B"
        for row in throughput_rows
    )
    recovery_exits = [
        float(row["exit_time_s"])
        for row in throughput_rows
        if row["service_phase"] == "recovery" and float(row["exit_time_s"]) > 0.0
    ]
    recovery_s = max(0.0, max(recovery_exits, default=1803.0) - 1803.0)
    if throughput_summary.get("report") != throughput_report:
        raise RuntimeError("throughput summary/report mismatch")
    if throughput_summary.get("result") == "pass" and not _all_true(throughput_summary.get("checks"), "throughput checks"):
        raise RuntimeError("throughput summary says pass while a source check is false")
    if int(throughput_report["arrivals"]) != throughput_arrivals:
        raise RuntimeError("throughput arrivals do not match throughput-items.csv")
    if int(throughput_report["exits"]) != throughput_exits or int(throughput_report["lost"]) != throughput_lost:
        raise RuntimeError("throughput exits/lost do not match throughput-items.csv")
    if int(throughput_report["duplicates"]) != throughput_duplicates:
        raise RuntimeError("throughput duplicate count does not match throughput-items.csv")
    if int(throughput_report["unsafe_to_b"]) != throughput_unsafe_b:
        raise RuntimeError("throughput unsafe-to-B count does not match throughput-items.csv")
    if abs(float(throughput_report["recovery_s"]) - recovery_s) > 1e-9:
        raise RuntimeError("throughput recovery duration does not match throughput-items.csv")
    if int(throughput_report["final_backlog"]) != throughput_lost:
        raise RuntimeError("throughput final backlog does not match raw item rows")
    if any(str(row.get("simulation_seed")) != str(throughput_report["seed"]) for row in throughput_events):
        raise RuntimeError("throughput event seed does not match report")
    _assert_file_provenance(throughput_dir, throughput_report.get("provenance"), "throughput provenance")
    expected_7200_claim = (
        "SUPPORTED"
        if throughput_arrivals >= 7200
        and throughput_exits == throughput_arrivals
        and throughput_lost == throughput_duplicates == throughput_unsafe_b == int(throughput_report["jams"]) == 0
        and recovery_s <= 5.0
        else "UNSUPPORTED"
    )
    if throughput_report.get("claim_7200_per_hour") != expected_7200_claim:
        raise RuntimeError("throughput 7200/h claim does not follow the locked qualification rule")
    if throughput_report.get("physical_safety_claim") is not False or "not physical Webots" not in str(
        throughput_report["evidence_scope"]
    ):
        raise RuntimeError("throughput evidence scope is not explicitly non-physical")

    ablations_summary = _load_json(ablations_dir / "ablations-summary.json")
    paired_results = _load_json(ablations_dir / "paired-results.json")
    predictor = _load_json(ablations_dir / "shadow-predictor.json")
    ablation_rows = _read_csv(ablations_dir / "ablation-trials.csv")
    ablation_json_rows = _read_jsonl(ablations_dir / "ablation-trials.jsonl")
    predictor_rows = _read_csv(ablations_dir / "shadow-predictor-rows.csv")
    if int(paired_results["raw_rows"]) != len(ablation_rows):
        raise RuntimeError("ablation raw row count does not match ablation-trials.csv")
    if len(ablation_rows) != len(ablation_json_rows):
        raise RuntimeError("ablation CSV/JSONL row counts disagree")
    csv_trial_ids = {
        (row["experiment"], row["variant"], row["pair_id"], row["input_hash"], row["metrics_json"])
        for row in ablation_rows
    }
    json_trial_ids = {
        (
            str(row["experiment"]),
            str(row["variant"]),
            str(row["pair_id"]),
            str(row["input_hash"]),
            json.dumps(row["metrics"], sort_keys=True, separators=(",", ":")),
        )
        for row in ablation_json_rows
    }
    if csv_trial_ids != json_trial_ids or len(csv_trial_ids) != len(ablation_rows):
        raise RuntimeError("ablation paired rows are duplicated or disagree across CSV/JSONL")
    _assert_file_provenance(ablations_dir, paired_results.get("provenance"), "ablation paired provenance")
    _assert_file_provenance(ablations_dir, predictor.get("provenance"), "shadow predictor provenance")
    if ablations_summary.get("predictor") != predictor:
        raise RuntimeError("ablation summary/predictor mismatch")
    if ablations_summary.get("result") == "pass" and not _all_true(ablations_summary.get("checks"), "ablation checks"):
        raise RuntimeError("ablation summary says pass while a source check is false")
    if predictor.get("actuation_authority") is not False or predictor.get("recommendation_channel") != "shadow_log_only":
        raise RuntimeError("shadow predictor is not isolated from actuation")
    test_predictor_rows = [row for row in predictor_rows if row["split"] == "test"]
    predictor_labels = [int(row["success"]) for row in test_predictor_rows]
    predictor_probabilities = [float(row["predicted_probability"]) for row in test_predictor_rows]
    baseline_probabilities = [float(row["baseline_probability"]) for row in test_predictor_rows]
    predictor_brier = _brier(predictor_labels, predictor_probabilities)
    baseline_brier = _brier(predictor_labels, baseline_probabilities)
    predictor_status = "IMPROVED" if predictor_brier < baseline_brier else "NO_GAIN"
    if (
        abs(float(predictor["brier_predictor"]) - predictor_brier) > 1e-12
        or abs(float(predictor["brier_constant_baseline"]) - baseline_brier) > 1e-12
        or predictor.get("status") != predictor_status
    ):
        raise RuntimeError("shadow predictor metrics do not match held-out raw rows")

    reliability_scope = str(reliability_report["evidence_model"])
    throughput_scope = str(throughput_report["evidence_scope"])
    ablations_scope = "computed paired deterministic trials and held-out shadow predictor; not physical Webots"
    records = {
        "reliability_numeric_routes": _metric(
            len(route_rows), "sources/reliability/routes.csv", "row_count", reliability_scope
        ),
        "reliability_numeric_accuracy": _metric(
            numeric_accuracy, "sources/reliability/routes.csv", "counted_correct/evaluated_rows", reliability_scope
        ),
        "reliability_automation_coverage": _metric(
            automation_coverage, "sources/reliability/routes.csv", "non_abstain/evaluated_rows", reliability_scope
        ),
        "reliability_unsafe_to_b": _metric(
            unsafe_to_b, "sources/reliability/routes.csv", "physical_exit=B AND truth IN (C,D)", reliability_scope
        ),
        "dimension_error_p95_mm": _metric(
            reliability_report["dimension_error_p95_mm"],
            "sources/reliability/statistical-report.json",
            "dimension_error_p95_mm",
            reliability_scope,
        ),
        "circularity_error_p95": _metric(
            reliability_report["k_error_p95"],
            "sources/reliability/statistical-report.json",
            "k_error_p95",
            reliability_scope,
        ),
        "throughput_arrivals": _metric(
            throughput_arrivals, "sources/throughput/throughput-items.csv", "row_count", throughput_scope
        ),
        "throughput_exits": _metric(
            throughput_exits, "sources/throughput/throughput-items.csv", "exit_time_s>0", throughput_scope
        ),
        "throughput_lost": _metric(
            throughput_lost, "sources/throughput/throughput-items.csv", "arrival_ids-exit_ids", throughput_scope
        ),
        "throughput_final_backlog": _metric(
            throughput_lost,
            "sources/throughput/throughput-items.csv",
            "arrivals-exits",
            throughput_scope,
        ),
        "throughput_7200_claim": _metric(
            throughput_report["claim_7200_per_hour"],
            "sources/throughput/claim-status.json",
            "result",
            throughput_scope,
        ),
        "ablation_trial_rows": _metric(
            len(ablation_rows), "sources/ablations/ablation-trials.csv", "row_count", ablations_scope
        ),
        "shadow_predictor_status": _metric(
            predictor_status,
            "sources/ablations/shadow-predictor-rows.csv",
            "derived_from_held_out_brier_comparison",
            ablations_scope,
        ),
        "shadow_predictor_brier": _metric(
            predictor_brier,
            "sources/ablations/shadow-predictor-rows.csv",
            "mean((predicted_probability-success)^2) WHERE split=test",
            ablations_scope,
        ),
        "shadow_baseline_brier": _metric(
            baseline_brier,
            "sources/ablations/shadow-predictor-rows.csv",
            "mean((baseline_probability-success)^2) WHERE split=test",
            ablations_scope,
        ),
    }
    source_results = {
        "ablations": ablations_summary.get("result"),
        "reliability": reliability_summary.get("result"),
        "throughput": throughput_summary.get("result"),
    }
    evidence_models = {
        "ablations": {"physical_webots_claim": False, "scope": ablations_scope},
        "reliability": {"physical_webots_claim": False, "scope": reliability_scope},
        "throughput": {"physical_webots_claim": False, "scope": throughput_scope},
    }
    return {
        "evidence_models": evidence_models,
        "metrics": {name: record["value"] for name, record in records.items()},
        "records": records,
        "source_results": source_results,
    }


def _write_source_provenance(run: Path) -> dict[str, str]:
    sources = run / "sources"
    provenance = {
        path.relative_to(run).as_posix(): _sha256(path)
        for path in sorted(sources.rglob("*"))
        if path.is_file()
    }
    atomic_json(
        run / "source-provenance.json",
        {"files": provenance, "hash_algorithm": "sha256", "schema_version": 1},
    )
    return provenance


def _copy_validated_webots_evidence(output: Path, *, requested: bool) -> dict[str, object]:
    if not requested:
        return {
            "physical_webots_claim": False,
            "reason": "record-video was not requested",
            "requested": False,
            "status": "not_requested",
        }
    supplied = os.environ.get("SAFESORT_WEBOTS_SMOKE_BUNDLE")
    if not supplied:
        return {
            "physical_webots_claim": False,
            "reason": "no validated Webots smoke bundle was supplied; no synthetic video was generated",
            "requested": True,
            "status": "not_included",
        }
    source = Path(supplied).resolve()
    try:
        from tools.smoke_cycle import verify_bundle

        verification = verify_bundle(source)
    except (OSError, RuntimeError, KeyError, TypeError, ValueError) as error:
        return {
            "physical_webots_claim": False,
            "reason": f"supplied Webots evidence failed verification: {type(error).__name__}",
            "requested": True,
            "status": "rejected",
        }
    source_manifest = _load_json(source / "manifest.json")
    capture = source_manifest.get("video_capture")
    capture_is_physical = (
        isinstance(capture, dict)
        and capture.get("source") == "webots-rendering"
        and capture.get("physics_mutation") is False
        and capture.get("schematic") is False
    )
    if not capture_is_physical:
        return {
            "physical_webots_claim": False,
            "reason": "supplied smoke bundle has no explicit read-only Webots-rendering capture provenance",
            "requested": True,
            "status": "rejected",
        }
    target = output / "webots-smoke"
    shutil.copytree(source, target)
    return {
        "bundle_manifest_sha256": _sha256(target / "manifest.json"),
        "physical_webots_claim": True,
        "requested": True,
        "status": "included",
        "verification_result": verification["result"],
        "video": "webots-smoke/smoke-trace.mp4",
    }


def _write_release_events(output: Path, aggregate: dict[str, object], provenance: dict[str, str]) -> str:
    records = aggregate["records"]
    if not isinstance(records, dict):
        raise RuntimeError("release metric records are invalid")
    events: list[dict[str, object]] = []
    for name, raw_record in sorted(records.items()):
        if not isinstance(raw_record, dict):
            raise RuntimeError(f"release metric record is invalid: {name}")
        source_file = str(raw_record["source_file"])
        events.append(
            {
                "evidence_scope": raw_record["evidence_scope"],
                "metric": name,
                "source_field": raw_record["source_field"],
                "source_file": f"runs/run-1/{source_file}",
                "source_sha256": provenance[source_file],
                "value": raw_record["value"],
            }
        )
    events_path = output / "release-events.jsonl"
    events_path.write_text(
        "".join(json.dumps(row, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n" for row in events),
        encoding="utf-8",
    )
    with (output / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("metric", "value_json", "source_file", "source_field", "source_sha256", "evidence_scope"),
        )
        writer.writeheader()
        for row in events:
            writer.writerow(
                {
                    "evidence_scope": row["evidence_scope"],
                    "metric": row["metric"],
                    "source_field": row["source_field"],
                    "source_file": row["source_file"],
                    "source_sha256": row["source_sha256"],
                    "value_json": json.dumps(row["value"], ensure_ascii=True, separators=(",", ":"), sort_keys=True),
                }
            )
    return _sha256(events_path)


def _write_reports(output: Path, aggregate: dict[str, object], source_event_hash: str) -> None:
    metrics = aggregate["metrics"]
    models = aggregate["evidence_models"]
    if not isinstance(metrics, dict) or not isinstance(models, dict):
        raise RuntimeError("release aggregate is invalid")
    metric_rows = "".join(
        f"<tr><th>{html.escape(str(name))}</th><td>{html.escape(str(value))}</td></tr>" for name, value in sorted(metrics.items())
    )
    model_rows = "".join(
        f"<li><strong>{html.escape(str(name))}</strong>: {html.escape(str(model['scope']))}</li>"
        for name, model in sorted(models.items())
        if isinstance(model, dict)
    )
    report_html = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>SafeSort release report</title>
<body><main><h1>SafeSort derived release evidence</h1>
<p>Source events SHA-256: <code>{source_event_hash}</code></p>
<p><strong>Scope:</strong> the metrics below are derived from numeric/proxy suites. They are not a physical Webots claim.</p>
<table>{metric_rows}</table><h2>Evidence models</h2><ul>{model_rows}</ul></main></body></html>
"""
    (output / "report.html").write_text(report_html, encoding="utf-8")
    (output / "report.pdf").write_bytes(
        _minimal_pdf(
            [
                "SafeSort derived release evidence",
                f"Source {source_event_hash[:20]}",
                f"Numeric routes {metrics['reliability_numeric_routes']}",
                f"Unsafe to B {metrics['reliability_unsafe_to_b']}",
                "Scope: numeric/proxy; not physical Webots",
            ]
        )
    )
    atomic_json(
        output / "kpi-overlay.json",
        {
            "evidence_models": models,
            "metrics": metrics,
            "physical_webots_claim": False,
            "source_event_hash": source_event_hash,
        },
    )


def generate_release_bundle(output: Path, repeat: int, seed: int, *, record_video: bool) -> dict[str, object]:
    if repeat < 1:
        raise RuntimeError("repeat must be positive")
    if output.exists():
        # Docker bind mounts cannot be removed as directories. Clear their
        # contents while preserving the mount point itself.
        for child in output.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
    output.mkdir(parents=True, exist_ok=True)

    semantic_hashes: list[str] = []
    source_provenance_hashes: list[str] = []
    aggregates: list[dict[str, object]] = []
    first_provenance: dict[str, str] = {}
    for index in range(1, repeat + 1):
        run = output / "runs" / f"run-{index}"
        for name, runner in _source_runners():
            source_output = run / "sources" / name
            source_output.mkdir(parents=True, exist_ok=True)
            runner(source_output, seed)
        aggregate = _aggregate_sources(run)
        provenance = _write_source_provenance(run)
        records = _object_dict(aggregate["records"], "records")
        for raw_record in records.values():
            record = _object_dict(raw_record, "metric record")
            record["source_sha256"] = provenance[str(record["source_file"])]
        semantic_payload = {
            "evidence_models": aggregate["evidence_models"],
            "metrics": aggregate["metrics"],
            "seed": seed,
            "source_results": aggregate["source_results"],
        }
        semantic_hash = _semantic_hash(semantic_payload)
        source_provenance_hash = _sha256(run / "source-provenance.json")
        source_pass = _sources_pass(aggregate)
        atomic_json(
            run / "summary.json",
            {
                **semantic_payload,
                "network": "none",
                "repeat": index,
                "semantic_hash": semantic_hash,
                "source_provenance_sha256": source_provenance_hash,
                "status": "PASS" if source_pass else "FAIL",
            },
        )
        aggregates.append(aggregate)
        semantic_hashes.append(semantic_hash)
        source_provenance_hashes.append(source_provenance_hash)
        if index == 1:
            first_provenance = provenance

    first = aggregates[0]
    source_event_hash = _write_release_events(output, first, first_provenance)
    _write_reports(output, first, source_event_hash)
    source_failures = sum(
        1
        for aggregate in aggregates
        if not _sources_pass(aggregate)
    )
    (output / "junit.xml").write_text(
        f'<testsuite name="release-derived-evidence" tests="{repeat}" failures="{source_failures}">'
        + "".join(f'<testcase name="derived-run-{index}"/>' for index in range(1, repeat + 1))
        + "</testsuite>\n",
        encoding="utf-8",
    )
    (output / "dashboard.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Judge dashboard</title>'
        f'<body><h1>Judge evidence dashboard</h1><p id="status">DERIVED EVIDENCE</p><p>Semantic hash: {semantic_hashes[0]}</p>'
        '<p>Numeric/proxy scope; no physical Webots claim.</p><a href="report.html">Open report</a></body></html>\n',
        encoding="utf-8",
    )
    video_evidence = _copy_validated_webots_evidence(output, requested=record_video)
    atomic_json(output / "video-evidence.json", video_evidence)

    all_sources_pass = all(_sources_pass(aggregate) for aggregate in aggregates)
    video_valid = video_evidence["status"] != "rejected"
    manifest: dict[str, object] = {
        "base_image_digest": (
            "cyberbotics/webots:R2025a-ubuntu22.04@sha256:f0023e30daf38b172e4e6ad24ed345909bcd9551df34d63d824e121a7cebf099"
        ),
        "commit": os.environ.get("SAFESORT_GIT_COMMIT", "unknown"),
        "config_hashes": _config_hashes(),
        "custom_image_digest": os.environ.get("SAFESORT_IMAGE_DIGEST", "local-build"),
        "dirty": os.environ.get("SAFESORT_GIT_DIRTY", "true") == "true",
        "evidence_models": first["evidence_models"],
        "first_image_download_excluded": True,
        "network": "none",
        "quick_start": {"commands": 3, "timing": "measure on target host; no duration asserted by this bundle"},
        "repeat": repeat,
        "seed": seed,
        "semantic_hashes": semantic_hashes,
        "source_event_hash": source_event_hash,
        "source_provenance_hashes": source_provenance_hashes,
        "tools": {"python": platform.python_version(), "webots_image": "R2025a"},
        "video_evidence": video_evidence,
    }
    atomic_json(output / "release-manifest.json", manifest)
    release_pass = repeat == 3 and len(set(semantic_hashes)) == 1 and all_sources_pass and video_valid
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "checksums.sha256")
    summary: dict[str, object] = {
        "artifacts": len(files) + 2,
        "evidence_models": first["evidence_models"],
        "metrics": first["metrics"],
        "record_video": record_video,
        "repeat": repeat,
        "result": "pass" if release_pass else "fail",
        "semantic_hashes": semantic_hashes,
        "video_evidence": video_evidence,
    }
    atomic_json(output / "release-summary.json", summary)
    files = sorted(path for path in output.rglob("*") if path.is_file() and path.name != "checksums.sha256")
    (output / "checksums.sha256").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(output).as_posix()}\n" for path in files), encoding="ascii"
    )
    return summary


def _check_checksums(bundle: Path) -> list[str]:
    checksum_path = bundle / "checksums.sha256"
    if not checksum_path.is_file():
        return ["checksums.sha256:MISSING"]
    failures: list[str] = []
    listed: set[str] = set()
    for index, line in enumerate(checksum_path.read_text(encoding="ascii").splitlines(), 1):
        try:
            digest, relative = line.split("  ", 1)
        except ValueError:
            failures.append(f"checksums.sha256:line-{index}")
            continue
        if (
            len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not _safe_relative_path(relative)
            or relative in listed
        ):
            failures.append(f"checksums.sha256:line-{index}")
            continue
        listed.add(relative)
        path = bundle / relative
        if not path.is_file() or _sha256(path) != digest:
            failures.append(relative)
    actual = {
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path.name != "checksums.sha256"
    }
    failures.extend(f"checksums.sha256:UNLISTED:{relative}" for relative in sorted(actual - listed))
    failures.extend(f"checksums.sha256:STALE:{relative}" for relative in sorted(listed - actual))
    return failures


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and "\\" not in value
        and not path.is_absolute()
        and ":" not in path.parts[0]
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
    )


def _check_source_provenance(bundle: Path) -> list[str]:
    failures: list[str] = []
    run_dirs = sorted(path for path in (bundle / "runs").glob("run-*") if path.is_dir())
    for run in run_dirs:
        provenance_path = run / "source-provenance.json"
        if not provenance_path.is_file():
            failures.append(provenance_path.relative_to(bundle).as_posix())
            continue
        run = provenance_path.parent
        try:
            provenance = _load_json(provenance_path)["files"]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            failures.append(provenance_path.relative_to(bundle).as_posix())
            continue
        if not isinstance(provenance, dict):
            failures.append(provenance_path.relative_to(bundle).as_posix())
            continue
        listed: set[str] = set()
        for relative, digest in provenance.items():
            relative_text = str(relative)
            if (
                not _safe_relative_path(relative_text)
                or not relative_text.startswith("sources/")
                or relative_text in listed
                or not isinstance(digest, str)
                or len(digest) != 64
            ):
                failures.append(f"{provenance_path.relative_to(bundle).as_posix()}:INVALID:{relative_text}")
                continue
            listed.add(relative_text)
            path = run / relative_text
            if not path.is_file() or _sha256(path) != digest:
                failures.append(path.relative_to(bundle).as_posix())
        actual = {
            path.relative_to(run).as_posix()
            for path in (run / "sources").rglob("*")
            if path.is_file()
        }
        failures.extend(
            f"{provenance_path.relative_to(bundle).as_posix()}:UNLISTED:{relative}"
            for relative in sorted(actual - listed)
        )
        failures.extend(
            f"{provenance_path.relative_to(bundle).as_posix()}:STALE:{relative}"
            for relative in sorted(listed - actual)
        )
    return failures


def _verify_derived_runs(bundle: Path, manifest: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    recomputed_hashes: list[str] = []
    expected_provenance_hashes = manifest.get("source_provenance_hashes", [])
    repeat = int(manifest["repeat"])
    expected_run_names = {f"run-{index}" for index in range(1, repeat + 1)}
    actual_run_names = {path.name for path in (bundle / "runs").glob("run-*") if path.is_dir()}
    if actual_run_names != expected_run_names:
        errors.append("runs:SET_MISMATCH")
    for index in range(1, repeat + 1):
        run = bundle / "runs" / f"run-{index}"
        try:
            aggregate = _aggregate_sources(run)
            summary = _load_json(run / "summary.json")
            semantic_payload = {
                "evidence_models": aggregate["evidence_models"],
                "metrics": aggregate["metrics"],
                "seed": manifest["seed"],
                "source_results": aggregate["source_results"],
            }
            semantic_hash = _semantic_hash(semantic_payload)
            recomputed_hashes.append(semantic_hash)
            if (
                summary.get("semantic_hash") != semantic_hash
                or summary.get("metrics") != aggregate["metrics"]
                or summary.get("evidence_models") != aggregate["evidence_models"]
                or summary.get("seed") != manifest["seed"]
                or summary.get("repeat") != index
                or summary.get("network") != "none"
            ):
                errors.append(f"runs/run-{index}/summary.json:DERIVATION_MISMATCH")
            if summary.get("source_results") != aggregate["source_results"]:
                errors.append(f"runs/run-{index}/summary.json:SOURCE_RESULT_MISMATCH")
            if not _sources_pass(aggregate):
                errors.append(f"runs/run-{index}:SOURCE_SUITE_FAILED")
            provenance_hash = _sha256(run / "source-provenance.json")
            expected_provenance_hash = (
                expected_provenance_hashes[index - 1]
                if isinstance(expected_provenance_hashes, list) and len(expected_provenance_hashes) >= index
                else None
            )
            if summary.get("source_provenance_sha256") != provenance_hash or expected_provenance_hash != provenance_hash:
                errors.append(f"runs/run-{index}/source-provenance.json:MANIFEST_MISMATCH")
        except (OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            errors.append(f"runs/run-{index}:{type(error).__name__}")
    return errors, recomputed_hashes


def _verify_events(bundle: Path, aggregate: dict[str, object]) -> list[str]:
    errors: list[str] = []
    try:
        events = _read_jsonl(bundle / "release-events.jsonl")
    except (OSError, RuntimeError):
        return ["release-events.jsonl:INVALID"]
    records = _object_dict(aggregate["records"], "release metric records")
    observed_names = [str(event.get("metric")) for event in events]
    if len(observed_names) != len(set(observed_names)) or set(observed_names) != set(records):
        errors.append("release-events.jsonl:METRIC_SET_MISMATCH")
    for event in events:
        metric = str(event.get("metric"))
        raw_record = records.get(metric)
        if not isinstance(raw_record, dict):
            continue
        relative_source = f"runs/run-1/{raw_record['source_file']}"
        if (
            event.get("value") != raw_record.get("value")
            or event.get("source_file") != relative_source
            or event.get("source_field") != raw_record.get("source_field")
            or event.get("evidence_scope") != raw_record.get("evidence_scope")
            or not _safe_relative_path(relative_source)
        ):
            errors.append(f"release-events.jsonl:DERIVATION_MISMATCH:{metric}")
            continue
        source = bundle / relative_source
        if not source.is_file() or _sha256(source) != event.get("source_sha256"):
            errors.append(f"release-events.jsonl:SOURCE_MISMATCH:{metric}")
    return errors


def _verify_presentation_data(
    bundle: Path,
    manifest: dict[str, Any],
    aggregate: dict[str, object],
    video_evidence: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    metrics = _object_dict(aggregate["metrics"], "release metrics")
    models = _object_dict(aggregate["evidence_models"], "evidence models")
    release_summary = _load_json(bundle / "release-summary.json")
    bundle_file_count = sum(path.is_file() for path in bundle.rglob("*"))
    expected_record_video = video_evidence.get("requested") is True
    if (
        release_summary.get("metrics") != metrics
        or release_summary.get("evidence_models") != models
        or release_summary.get("semantic_hashes") != manifest.get("semantic_hashes")
        or release_summary.get("repeat") != manifest.get("repeat")
        or release_summary.get("video_evidence") != video_evidence
        or release_summary.get("record_video") is not expected_record_video
        or release_summary.get("artifacts") != bundle_file_count
        or release_summary.get("result") != "pass"
    ):
        errors.append("release-summary.json:DERIVATION_MISMATCH")
    overlay = _load_json(bundle / "kpi-overlay.json")
    if overlay != {
        "evidence_models": models,
        "metrics": metrics,
        "physical_webots_claim": False,
        "source_event_hash": manifest.get("source_event_hash"),
    }:
        errors.append("kpi-overlay.json:DERIVATION_MISMATCH")
    result_rows = _read_csv(bundle / "results.csv")
    event_rows = _read_jsonl(bundle / "release-events.jsonl")
    expected_rows = {
        (
            str(row["metric"]),
            json.dumps(row["value"], ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            str(row["source_file"]),
            str(row["source_field"]),
            str(row["source_sha256"]),
            str(row["evidence_scope"]),
        )
        for row in event_rows
    }
    observed_rows = {
        (
            row["metric"],
            row["value_json"],
            row["source_file"],
            row["source_field"],
            row["source_sha256"],
            row["evidence_scope"],
        )
        for row in result_rows
    }
    if expected_rows != observed_rows or len(result_rows) != len(event_rows):
        errors.append("results.csv:DERIVATION_MISMATCH")
    report = (bundle / "report.html").read_text(encoding="utf-8")
    source_event_hash = manifest.get("source_event_hash")
    if not isinstance(source_event_hash, str) or source_event_hash not in report or any(
        html.escape(str(value)) not in report for value in metrics.values()
    ):
        errors.append("report.html:DERIVATION_MISMATCH")
    expected_pdf = _minimal_pdf(
        [
            "SafeSort derived release evidence",
            f"Source {str(source_event_hash)[:20]}",
            f"Numeric routes {metrics.get('reliability_numeric_routes')}",
            f"Unsafe to B {metrics.get('reliability_unsafe_to_b')}",
            "Scope: numeric/proxy; not physical Webots",
        ]
    )
    if (bundle / "report.pdf").read_bytes() != expected_pdf:
        errors.append("report.pdf:DERIVATION_MISMATCH")
    dashboard = (bundle / "dashboard.html").read_text(encoding="utf-8")
    hashes = manifest.get("semantic_hashes", [])
    if not isinstance(hashes, list) or not hashes or str(hashes[0]) not in dashboard or "no physical Webots claim" not in dashboard:
        errors.append("dashboard.html:DERIVATION_MISMATCH")
    expected_junit = (
        f'<testsuite name="release-derived-evidence" tests="{manifest.get("repeat")}" failures="0">'
        + "".join(
            f'<testcase name="derived-run-{index}"/>' for index in range(1, int(manifest.get("repeat", 0)) + 1)
        )
        + "</testsuite>\n"
    )
    if (bundle / "junit.xml").read_text(encoding="utf-8") != expected_junit:
        errors.append("junit.xml:DERIVATION_MISMATCH")
    return errors


def verify_release_bundle(bundle: Path, *, tamper_canary: bool) -> dict[str, object]:
    required = (
        "checksums.sha256",
        "dashboard.html",
        "junit.xml",
        "kpi-overlay.json",
        "release-events.jsonl",
        "release-manifest.json",
        "release-summary.json",
        "report.html",
        "report.pdf",
        "results.csv",
        "video-evidence.json",
    )
    missing_required = [name for name in required if not (bundle / name).is_file()]
    if missing_required:
        return {
            "checks": {"artifacts_present": False},
            "checksum_failures": missing_required,
            "result": "fail",
            "source_provenance_failures": [],
            "tamper_detected": False,
            "tamper_restored": False,
        }
    manifest = _load_json(bundle / "release-manifest.json")
    initial_failures = _check_checksums(bundle)
    provenance_failures = _check_source_provenance(bundle)
    derivation_errors, recomputed_hashes = _verify_derived_runs(bundle, manifest)
    try:
        first_aggregate = _aggregate_sources(bundle / "runs" / "run-1")
    except (OSError, KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        first_aggregate = {"evidence_models": {}, "metrics": {}, "records": {}, "source_results": {}}
    event_errors = _verify_events(bundle, first_aggregate)
    event_hash_matches = _sha256(bundle / "release-events.jsonl") == manifest.get("source_event_hash")

    video_evidence = _load_json(bundle / "video-evidence.json")
    video_status = video_evidence.get("status")
    video_valid = video_status in {"not_requested", "not_included"} and video_evidence.get("physical_webots_claim") is False
    if video_status == "included":
        try:
            from tools.smoke_cycle import verify_bundle

            copied_manifest = _load_json(bundle / "webots-smoke" / "manifest.json")
            capture = copied_manifest.get("video_capture")
            capture_is_physical = (
                isinstance(capture, dict)
                and capture.get("source") == "webots-rendering"
                and capture.get("physics_mutation") is False
                and capture.get("schematic") is False
            )
            video_valid = verify_bundle(bundle / "webots-smoke")["result"] == "pass" and capture_is_physical
        except (OSError, RuntimeError, KeyError, TypeError, ValueError):
            video_valid = False
    presentation_errors = _verify_presentation_data(bundle, manifest, first_aggregate, video_evidence)

    tamper_detected = restored = False
    if tamper_canary:
        target = bundle / "runs" / "run-1" / "sources" / "reliability" / "routes.csv"
        original = target.read_bytes()
        target.write_bytes(original + b"# tamper canary\n")
        tamper_detected = bool(_check_checksums(bundle) or _check_source_provenance(bundle))
        target.write_bytes(original)
        restored = not _check_checksums(bundle) and not _check_source_provenance(bundle)

    semantic_identical = (
        int(manifest.get("repeat", 0)) == 3
        and len(recomputed_hashes) == 3
        and len(set(recomputed_hashes)) == 1
        and recomputed_hashes == manifest.get("semantic_hashes")
    )
    models = manifest.get("evidence_models", {})
    evidence_labels_honest = isinstance(models, dict) and bool(models) and all(
        isinstance(model, dict)
        and model.get("physical_webots_claim") is False
        and ("not physical Webots" in str(model.get("scope", "")) or "proxy" in str(model.get("scope", "")))
        for model in models.values()
    )
    config_hashes = manifest.get("config_hashes")
    config_provenance = isinstance(config_hashes, dict) and bool(config_hashes) and config_hashes == _config_hashes()
    manifest_matches_sources = (
        manifest.get("evidence_models") == first_aggregate.get("evidence_models")
        and manifest.get("semantic_hashes") == recomputed_hashes
        and manifest.get("video_evidence") == video_evidence
    )
    checks = {
        "all_checksums": not initial_failures,
        "artifacts_present": not missing_required,
        "commit_recorded": manifest.get("commit") != "unknown",
        "config_provenance": config_provenance,
        "derived_metrics_recomputed": not derivation_errors,
        "event_provenance": not event_errors and event_hash_matches,
        "evidence_labels_honest": evidence_labels_honest,
        "manifest_matches_sources": manifest_matches_sources,
        "network_none": manifest.get("network") == "none",
        "no_synthetic_physical_trace": not (bundle / "trajectory.jsonl").exists() and not (bundle / "smoke-trace.mp4").exists(),
        "presentation_data_derived": not presentation_errors,
        "quick_start": int(manifest.get("quick_start", {}).get("commands", 999)) <= 3,
        "semantic_identical": semantic_identical,
        "source_tree_clean": manifest.get("dirty") is False,
        "source_provenance": not provenance_failures,
        "tamper_detected": not tamper_canary or (tamper_detected and restored),
        "video_evidence_valid": video_valid,
    }
    return {
        "checks": checks,
        "checksum_failures": initial_failures,
        "derivation_errors": derivation_errors,
        "event_errors": event_errors,
        "presentation_errors": presentation_errors,
        "result": "pass" if all(checks.values()) else "fail",
        "source_provenance_failures": provenance_failures,
        "tamper_detected": tamper_detected,
        "tamper_restored": restored,
    }

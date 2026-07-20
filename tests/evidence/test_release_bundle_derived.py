from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from tools import release_bundle, smoke_cycle


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_checksums(bundle: Path) -> None:
    files = sorted(path for path in bundle.rglob("*") if path.is_file() and path.name != "checksums.sha256")
    (bundle / "checksums.sha256").write_text(
        "".join(f"{_sha256(path)}  {path.relative_to(bundle).as_posix()}\n" for path in files),
        encoding="ascii",
    )


def _generate_fake_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    monkeypatch.setattr(
        release_bundle,
        "_source_runners",
        lambda: (
            ("reliability", _fake_reliability),
            ("throughput", _fake_throughput),
            ("ablations", _fake_ablations),
        ),
    )
    monkeypatch.setenv("SAFESORT_GIT_COMMIT", "0123456789abcdef")
    monkeypatch.setenv("SAFESORT_GIT_DIRTY", "false")
    monkeypatch.delenv("SAFESORT_WEBOTS_SMOKE_BUNDLE", raising=False)
    bundle = tmp_path / "release"
    summary = release_bundle.generate_release_bundle(bundle, repeat=3, seed=20260718, record_video=True)
    return bundle, cast(dict[str, Any], summary)


def _verify(bundle: Path, *, tamper_canary: bool) -> dict[str, Any]:
    return cast(dict[str, Any], release_bundle.verify_release_bundle(bundle, tamper_canary=tamper_canary))


def _fake_reliability(output: Path, seed: int) -> dict[str, object]:
    del seed
    rows = [
        {
            "counted_correct": True,
            "decision": "B",
            "item_id": "public-1",
            "physical_exit": "B",
            "suite": "public",
            "truth": "B",
        },
        {
            "counted_correct": False,
            "decision": "ABSTAIN_C",
            "item_id": "blind-1",
            "physical_exit": "C",
            "suite": "blind",
            "truth": "B",
        },
        {
            "counted_correct": False,
            "decision": "C",
            "item_id": "fault-1",
            "physical_exit": "C",
            "suite": "fault",
            "truth": "C",
        },
    ]
    _write_csv(output / "routes.csv", rows)
    report = {
        "automation_coverage": 0.5,
        "dimension_error_p95_mm": 7.25,
        "duplicates": 0,
        "evidence_model": "test five-view sensor + conveyor-proxy",
        "k_error_p95": 0.14,
        "lost": 0,
        "official_accuracy": 0.5,
        "physical_webots_claim": False,
        "total_numeric_routes": 3,
        "unsafe_to_b": 0,
    }
    _write_json(output / "statistical-report.json", report)
    _write_json(
        output / "locked-suites.json",
        {"evidence_model": report["evidence_model"], "physical_webots_claim": False},
    )
    summary = {"physical_smoke_required_separately": True, "report": report, "result": "pass"}
    _write_json(output / "reliability-summary.json", summary)
    return summary


def _fake_throughput(output: Path, seed: int) -> dict[str, object]:
    items = [
        {
            "decision_before_deadline": True,
            "exit_time_s": 1.0,
            "item_id": 1,
            "selected_route": "B",
            "service_phase": "nominal",
        },
        {
            "decision_before_deadline": True,
            "exit_time_s": 2.0,
            "item_id": 2,
            "selected_route": "C",
            "service_phase": "nominal",
        },
    ]
    _write_csv(output / "throughput-items.csv", items)
    _write_jsonl(
        output / "throughput-events.jsonl",
        [{"event": "arrival", "item_id": row["item_id"], "simulation_seed": seed} for row in items],
    )
    _write_csv(output / "hour-flow.csv", [{"arrivals": 2, "backlog": 0, "exits": 2, "second": 1}])
    provenance = {
        name: _sha256(output / name)
        for name in ("hour-flow.csv", "throughput-events.jsonl", "throughput-items.csv")
    }
    report = {
        "arrivals": 2,
        "claim_7200_per_hour": "UNSUPPORTED",
        "duplicates": 0,
        "evidence_scope": "test discrete-event proxy; not physical Webots",
        "exits": 2,
        "final_backlog": 0,
        "jams": 0,
        "lost": 0,
        "physical_safety_claim": False,
        "provenance": provenance,
        "recovery_s": 0.0,
        "seed": seed,
        "unsafe_to_b": 0,
    }
    _write_json(output / "throughput-report.json", report)
    _write_json(
        output / "claim-status.json",
        {
            "claim": "7200 items/hour",
            "evidence_scope": report["evidence_scope"],
            "required_spacing_m": 0.5,
            "result": report["claim_7200_per_hour"],
            "supported_profile": "fixture",
        },
    )
    summary = {"checks": {"fixture_valid": True}, "report": report, "result": "pass"}
    _write_json(output / "hour-flow-summary.json", summary)
    return summary


def _fake_ablations(output: Path, seed: int) -> dict[str, object]:
    metrics = {"loss": 3.0}
    trial_json: dict[str, object] = {
        "experiment": "paired",
        "input_hash": "input-1",
        "metrics": metrics,
        "pair_id": "pair-1",
        "variant": "baseline",
    }
    trial_csv: dict[str, object] = {
        "experiment": trial_json["experiment"],
        "input_hash": trial_json["input_hash"],
        "metrics_json": json.dumps(metrics, sort_keys=True, separators=(",", ":")),
        "pair_id": trial_json["pair_id"],
        "variant": trial_json["variant"],
    }
    _write_csv(output / "ablation-trials.csv", [trial_csv])
    _write_jsonl(output / "ablation-trials.jsonl", [trial_json])
    paired = {
        "provenance": {
            "ablation-trials.csv": _sha256(output / "ablation-trials.csv"),
            "ablation-trials.jsonl": _sha256(output / "ablation-trials.jsonl"),
        },
        "raw_rows": 1,
    }
    _write_json(output / "paired-results.json", paired)
    predictor_rows: list[dict[str, object]] = [
        {
            "baseline_probability": 0.5,
            "predicted_probability": 0.8,
            "split": "test",
            "success": 1,
        },
        {
            "baseline_probability": 0.5,
            "predicted_probability": 0.2,
            "split": "test",
            "success": 0,
        },
    ]
    _write_csv(output / "shadow-predictor-rows.csv", predictor_rows)
    _write_jsonl(output / "shadow-predictor-rows.jsonl", predictor_rows)
    predictor = {
        "actuation_authority": False,
        "brier_constant_baseline": 0.25,
        "brier_predictor": 0.04,
        "provenance": {
            "shadow-predictor-rows.csv": _sha256(output / "shadow-predictor-rows.csv"),
            "shadow-predictor-rows.jsonl": _sha256(output / "shadow-predictor-rows.jsonl"),
        },
        "recommendation_channel": "shadow_log_only",
        "status": "IMPROVED",
    }
    _write_json(output / "shadow-predictor.json", predictor)
    summary = {"checks": {"fixture_valid": True}, "predictor": predictor, "result": "pass"}
    _write_json(output / "ablations-summary.json", summary)
    return summary


def test_release_metrics_are_derived_and_raw_tamper_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, summary = _generate_fake_bundle(tmp_path, monkeypatch)

    assert summary["result"] == "pass"
    assert summary["metrics"]["reliability_numeric_routes"] == 3
    assert summary["metrics"]["reliability_numeric_accuracy"] == 0.5
    assert summary["metrics"]["dimension_error_p95_mm"] == 7.25
    assert summary["metrics"]["throughput_arrivals"] == 2
    assert summary["metrics"]["ablation_trial_rows"] == 1
    assert summary["metrics"]["shadow_predictor_brier"] == pytest.approx(0.04)
    assert summary["video_evidence"]["status"] == "not_included"
    assert not (bundle / "trajectory.jsonl").exists()
    assert not (bundle / "smoke-trace.mp4").exists()

    verification = _verify(bundle, tamper_canary=True)
    assert verification["result"] == "pass"
    assert verification["tamper_detected"] is True
    assert verification["tamper_restored"] is True

    raw_routes = bundle / "runs" / "run-1" / "sources" / "reliability" / "routes.csv"
    raw_routes.write_text(raw_routes.read_text(encoding="utf-8") + "false,B,B,blind,B\n", encoding="utf-8")
    tampered = _verify(bundle, tamper_canary=False)
    assert tampered["result"] == "fail"
    assert tampered["checks"]["all_checksums"] is False
    assert tampered["checks"]["source_provenance"] is False


def test_checksum_index_must_cover_every_bundle_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle, _ = _generate_fake_bundle(tmp_path, monkeypatch)
    checksum_path = bundle / "checksums.sha256"
    checksum_path.write_text(
        "\n".join(line for line in checksum_path.read_text(encoding="ascii").splitlines() if not line.endswith("  report.html"))
        + "\n",
        encoding="ascii",
    )

    verification = _verify(bundle, tamper_canary=False)

    assert verification["result"] == "fail"
    assert verification["checks"]["all_checksums"] is False
    assert "checksums.sha256:UNLISTED:report.html" in verification["checksum_failures"]


def test_rehashed_presentation_tamper_is_rejected_semantically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _ = _generate_fake_bundle(tmp_path, monkeypatch)
    overlay_path = bundle / "kpi-overlay.json"
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    overlay["metrics"]["reliability_numeric_accuracy"] = 1.0
    _write_json(overlay_path, overlay)
    _rewrite_checksums(bundle)

    verification = _verify(bundle, tamper_canary=False)

    assert verification["checks"]["all_checksums"] is True
    assert verification["checks"]["presentation_data_derived"] is False
    assert "kpi-overlay.json:DERIVATION_MISMATCH" in verification["presentation_errors"]


def test_duplicate_release_event_is_rejected_even_after_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _ = _generate_fake_bundle(tmp_path, monkeypatch)
    events_path = bundle / "release-events.jsonl"
    first = events_path.read_text(encoding="utf-8").splitlines()[0]
    events_path.write_text(events_path.read_text(encoding="utf-8") + first + "\n", encoding="utf-8")
    _rewrite_checksums(bundle)

    verification = _verify(bundle, tamper_canary=False)

    assert verification["checks"]["all_checksums"] is True
    assert verification["checks"]["event_provenance"] is False
    assert "release-events.jsonl:METRIC_SET_MISMATCH" in verification["event_errors"]


def test_dirty_release_manifest_is_rejected_even_after_rehash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _ = _generate_fake_bundle(tmp_path, monkeypatch)
    manifest_path = bundle / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["dirty"] = True
    _write_json(manifest_path, manifest)
    _rewrite_checksums(bundle)

    verification = _verify(bundle, tamper_canary=False)

    assert verification["result"] == "fail"
    assert verification["checks"]["source_tree_clean"] is False


def test_schematic_smoke_video_cannot_be_promoted_to_physical_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "legacy-smoke"
    source.mkdir()
    _write_json(source / "manifest.json", {"files": {}, "scenario": "legacy"})
    monkeypatch.setenv("SAFESORT_WEBOTS_SMOKE_BUNDLE", str(source))
    monkeypatch.setattr(smoke_cycle, "verify_bundle", lambda bundle: {"result": "pass", "video": str(bundle)})

    result = release_bundle._copy_validated_webots_evidence(tmp_path / "release", requested=True)

    assert result["status"] == "rejected"
    assert result["physical_webots_claim"] is False
    assert "Webots-rendering" in str(result["reason"])

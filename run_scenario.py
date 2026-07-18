"""Single host entry point for deterministic Docker-based SafeSort workflows."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = "deca123-sim:dev"
sys.path.insert(0, str(ROOT / "src"))


def emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def docker_environment() -> tuple[dict[str, str], Path]:
    """Use an isolated credential-free Docker config for reproducible public pulls."""
    config_dir = ROOT / ".runtime" / "docker-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    if not config_file.exists():
        config_file.write_text('{"auths": {}}\n', encoding="utf-8")
    env = os.environ.copy()
    env["DOCKER_CONFIG"] = str(config_dir)
    return env, config_dir


def run_checked(command: Sequence[str], *, env: dict[str, str] | None = None) -> int:
    completed = subprocess.run(list(command), cwd=ROOT, env=env, check=False)
    return completed.returncode


def docker_executable() -> str:
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("Docker CLI is not installed or not on PATH")
    return executable


def webots_version() -> str:
    version_file = Path("/usr/local/webots/resources/version.txt")
    executable = Path("/usr/local/webots/webots")
    if version_file.is_file() and executable.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
        if version:
            return version
    candidates = [shutil.which("webots"), "/usr/local/webots/webots"]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            completed = subprocess.run([candidate, "--version"], capture_output=True, text=True, check=False)
            text = (completed.stdout or completed.stderr).strip()
            if completed.returncode == 0 and text:
                return text.splitlines()[-1]
    return "unavailable"


def command_image_build(tag: str) -> int:
    env, config_dir = docker_environment()
    emit(
        {
            "action": "docker-build",
            "credential_copy_count": 0,
            "docker_config": str(config_dir.relative_to(ROOT)),
            "tag": tag,
        }
    )
    return run_checked(
        [
            docker_executable(),
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--load",
            "-t",
            tag,
            ".",
        ],
        env=env,
    )


def command_doctor(require_container: bool, inside_container: bool, tag: str) -> int:
    if inside_container:
        version = webots_version()
        payload: dict[str, object] = {
            "execution_mode": "cpu",
            "gpu_required": False,
            "inside_container": True,
            "machine": platform.machine(),
            "platform": platform.platform(),
            "platform_target": "linux/amd64",
            "python": platform.python_version(),
            "webots": version,
        }
        emit(payload)
        return 0 if version != "unavailable" and platform.python_version().startswith("3.12") else 1

    env, config_dir = docker_environment()
    emit(
        {
            "credential_copy_count": 0,
            "docker_config": str(config_dir.relative_to(ROOT)),
            "gpu_required": False,
            "host_python": platform.python_version(),
        }
    )
    if not require_container:
        return 0
    return run_checked(
        [
            docker_executable(),
            "run",
            "--rm",
            "--network",
            "none",
            "-e",
            "SAFESORT_IN_CONTAINER=1",
            tag,
            "doctor",
            "--inside-container",
        ],
        env=env,
    )


def command_contract_validate(inside_container: bool, tag: str) -> int:
    if not inside_container:
        env, _ = docker_environment()
        return run_checked(
            [
                docker_executable(),
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "SAFESORT_IN_CONTAINER=1",
                tag,
                "contract",
                "validate",
                "--inside-container",
            ],
            env=env,
        )

    from safesort.contracts.acceptance import validate_contract

    summary = validate_contract()
    summary["result"] = "pass"
    emit(summary)
    return 0


def command_architecture_verify(inside_container: bool, tag: str) -> int:
    if not inside_container:
        env, _ = docker_environment()
        return run_checked(
            [
                docker_executable(),
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "SAFESORT_IN_CONTAINER=1",
                tag,
                "architecture",
                "verify",
                "--inside-container",
            ],
            env=env,
        )

    from tools.check_architecture import verify_architecture

    summary = verify_architecture()
    summary["result"] = "pass"
    emit(summary)
    return 0


def command_evaluator_validate(output_value: str, inside_container: bool, tag: str) -> int:
    if inside_container:
        from tools.evaluator_validate import validate

        summary = validate(Path(output_value))
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    output = _workspace_output(output_value)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    if command_image_build(tag) != 0:
        return 1
    env, _ = docker_environment()
    return run_checked(
        [
            docker_executable(),
            "run",
            "--rm",
            "--network",
            "none",
            "-v",
            f"{output}:/output",
            tag,
            "evaluator",
            "validate",
            "--output",
            "/output",
            "--inside-container",
        ],
        env=env,
    )


def command_quality(checks: str, inside_container: bool, tag: str) -> int:
    if checks not in {"bootstrap", "contract", "architecture", "sensing", "geometry", "rules,ledger,deadlines"}:
        emit({"error": "quality profile is not implemented yet", "profile": checks})
        return 2

    if not inside_container:
        env, _ = docker_environment()
        return run_checked(
            [
                docker_executable(),
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "SAFESORT_IN_CONTAINER=1",
                tag,
                "quality",
                "--checks",
                checks,
                "--inside-container",
            ],
            env=env,
        )

    test_paths = ["tests/smoke", "tests/simulation"]
    if checks in {"contract", "architecture", "sensing", "geometry"}:
        test_paths.append("tests/contract")
    if checks in {"architecture", "sensing", "geometry"}:
        test_paths.append("tests/architecture")
    if checks in {"sensing", "geometry"}:
        test_paths.append("tests/sensing")
    if checks == "geometry":
        test_paths.append("tests/geometry")
    if checks == "rules,ledger,deadlines":
        test_paths.append("tests/scheduling")
    commands = [
        [sys.executable, "-m", "compileall", "-q", "src", "tools", "run_scenario.py"],
        [sys.executable, "-m", "ruff", "check", "src", "tests", "tools", "run_scenario.py"],
        [sys.executable, "-m", "mypy", "src", "run_scenario.py", "tools"],
        [sys.executable, "-m", "pytest", *test_paths, "-q"],
    ]
    if checks in {"contract", "architecture", "sensing", "geometry"}:
        commands.extend(
            [
                [sys.executable, "tools/render_acceptance_matrix.py", "--check"],
                [
                    sys.executable,
                    "run_scenario.py",
                    "contract",
                    "validate",
                    "--inside-container",
                ],
            ]
        )
    if checks in {"architecture", "sensing", "geometry"}:
        commands.extend(
            [
                [
                    sys.executable,
                    "run_scenario.py",
                    "architecture",
                    "verify",
                    "--inside-container",
                ],
                [sys.executable, "tools/leak_test.py", "--with-canary"],
            ]
        )
    if checks in {"sensing", "geometry"}:
        commands.append(
            [
                sys.executable,
                "tools/verify_calibration.py",
                "--config",
                "config/calibration/calibration.yaml",
            ]
        )
    for command in commands:
        code = run_checked(command)
        if code != 0:
            return code
    if checks == "rules,ledger,deadlines":
        from tools.scheduling_checks import run_checks

        emit(run_checks())
    emit({"checks": checks, "result": "pass"})
    return 0


def _workspace_output(path: str) -> Path:
    output = Path(path).resolve()
    if not output.is_relative_to(ROOT):
        raise RuntimeError("host output must stay inside the repository")
    return output


def _run_smoke_container(
    scenario: str,
    seed: int,
    output: Path,
    tag: str,
    *,
    canary: bool,
) -> int:
    env, _ = docker_environment()
    output.mkdir(parents=True, exist_ok=True)
    command = [
        docker_executable(),
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "-e",
        "SAFESORT_IN_CONTAINER=1",
        "-v",
        f"{output}:/output",
        tag,
        "run",
        "--scenario",
        scenario,
        "--seed",
        str(seed),
        "--output",
        "/output",
        "--inside-container",
    ]
    if canary:
        command.append("--canary")
    return run_checked(command, env=env)


def _read_result_status(output: Path) -> str | None:
    result = output / "evaluator-result.json"
    if not result.is_file():
        return None
    payload = json.loads(result.read_text(encoding="utf-8"))
    return str(payload.get("result")) if isinstance(payload, dict) else None


def _inside_smoke_run(scenario: str, seed: int, output: Path, *, canary: bool) -> int:
    from tools.smoke_cycle import create_trace_video, validate_scene, write_manifest

    scenario_path = ROOT / scenario
    scene = validate_scene(scenario_path, output)
    world = ROOT / str(json.loads(scenario_path.read_text(encoding="utf-8"))["world"])
    env = os.environ.copy()
    env.update(
        {
            "PYTHONHASHSEED": "0",
            "QTWEBENGINE_DISABLE_SANDBOX": "1",
            "SAFESORT_DISABLE_EXIT": "1" if canary else "0",
            "SAFESORT_OUTPUT_DIR": str(output),
            "SAFESORT_SEED": str(seed),
        }
    )
    command = [
        "xvfb-run",
        "-a",
        "/usr/local/webots/webots",
        "--batch",
        "--mode=fast",
        "--minimize",
        "--stdout",
        "--stderr",
        str(world),
    ]
    try:
        completed = subprocess.run(command, cwd=ROOT, env=env, check=False, timeout=90)
        exit_code = completed.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
    status = _read_result_status(output)
    if canary and status == "FAULT":
        exit_code = 3
    elif not canary and status == "SUCCESS":
        exit_code = 0
    elif exit_code == 0:
        exit_code = 2
    if not canary and exit_code == 0:
        create_trace_video(output)
    manifest = write_manifest(output, scenario, seed, exit_code, canary=canary)
    emit(
        {
            "canary": canary,
            "exit_code": exit_code,
            "network": "none",
            "result": status or "missing",
            "scene": scene["result"],
            "semantic_trace_hash": manifest["semantic_trace_hash"],
        }
    )
    return exit_code


def command_run(
    scenario: str,
    seed: int,
    output_value: str,
    inside_container: bool,
    tag: str,
    *,
    canary: bool,
    repeat: int = 1,
) -> int:
    if scenario.endswith("power_loss.yaml"):
        output = _workspace_output(output_value)
        if output.exists():
            shutil.rmtree(output)
        output.mkdir(parents=True)
        if command_image_build(tag) != 0:
            return 1
        env, _ = docker_environment()
        return run_checked(
            [
                docker_executable(),
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{output}:/output",
                "--entrypoint",
                "python",
                tag,
                "tools/gate_trials.py",
                "--repeat",
                str(repeat),
                "--seed",
                str(seed),
                "--output",
                "/output",
            ],
            env=env,
        )
    if inside_container:
        return _inside_smoke_run(scenario, seed, Path(output_value), canary=canary)
    output = _workspace_output(output_value)
    if output.exists():
        shutil.rmtree(output)
    if command_image_build(tag) != 0:
        return 1
    nominal_code = _run_smoke_container(scenario, seed, output, tag, canary=False)
    canary_output = output / "canary"
    canary_code = _run_smoke_container(scenario, seed, canary_output, tag, canary=True)
    summary = {
        "canary_exit_code": canary_code,
        "canary_expected_nonzero": canary_code != 0,
        "network": "none",
        "nominal_exit_code": nominal_code,
        "result": "pass" if nominal_code == 0 and canary_code != 0 else "fail",
    }
    (output / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    emit(summary)
    return 0 if summary["result"] == "pass" else 1


def command_replay(bundle_value: str, repeat: int, tag: str) -> int:
    from tools.smoke_cycle import load_object

    if repeat < 2:
        raise RuntimeError("repeat must be at least 2")
    bundle = _workspace_output(bundle_value)
    manifest = load_object(bundle / "manifest.json")
    scenario = str(manifest["scenario"])
    seed = int(manifest["seed"])
    replay_root = bundle / "replay"
    if replay_root.exists():
        shutil.rmtree(replay_root)
    hashes: list[str] = []
    for index in range(1, repeat + 1):
        target = replay_root / f"run-{index}"
        code = _run_smoke_container(scenario, seed, target, tag, canary=False)
        if code != 0:
            emit({"failed_repeat": index, "result": "fail"})
            return 1
        replay_manifest = load_object(target / "manifest.json")
        hashes.append(str(replay_manifest["semantic_trace_hash"]))
    identical = len(set(hashes)) == 1
    payload = {"hashes": hashes, "identical": identical, "repeat": repeat, "result": "pass" if identical else "fail"}
    (bundle / "replay.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    emit(payload)
    return 0 if identical else 1


def command_verify_bundle(bundle_value: str, *, tamper_canary: bool = False) -> int:
    bundle = _workspace_output(bundle_value)
    if (bundle / "release-manifest.json").is_file():
        from tools.release_bundle import verify_release_bundle

        summary = verify_release_bundle(bundle, tamper_canary=tamper_canary)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    if (bundle / "reliability-summary.json").is_file():
        from tools.reliability_suite import verify_reliability_bundle

        summary = verify_reliability_bundle(bundle)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    from tools.smoke_cycle import SmokeEvidenceError, verify_bundle

    try:
        summary = verify_bundle(bundle)
    except SmokeEvidenceError as error:
        emit({"error": str(error), "result": "fail"})
        return 1
    emit(summary)
    return 0


def _run_suite_container(
    profile: str,
    seed: int,
    output: Path,
    tag: str,
    *,
    repeat: int = 1,
    record_video: bool = False,
    environment: dict[str, str] | None = None,
) -> int:
    env, _ = docker_environment()
    output.mkdir(parents=True, exist_ok=True)
    command = [
        docker_executable(),
        "run",
        "--rm",
        "--network",
        "none",
        "--cpus",
        "2",
        "--memory",
        "4g",
    ]
    for key, value in sorted((environment or {}).items()):
        command.extend(("-e", f"{key}={value}"))
    command.extend(
        (
            "-v",
            f"{output}:/output",
            tag,
            "suite",
            "--profile",
            profile,
            "--seed",
            str(seed),
            "--repeat",
            str(repeat),
            "--output",
            "/output",
            "--inside-container",
        )
    )
    if record_video:
        command.append("--record-video")
    return run_checked(command, env=env)


def command_suite(
    profile: str,
    seed: int,
    output_value: str,
    tag: str,
    *,
    inside_container: bool,
    repeat: int = 1,
    record_video: bool = False,
) -> int:
    if profile not in {
        "sensing",
        "geometry",
        "uncertainty",
        "gates",
        "reliability-release",
        "hour-flow",
        "ablations",
        "release",
    }:
        emit({"error": "suite profile is not implemented yet", "profile": profile})
        return 2
    if profile == "geometry" and inside_container:
        from tools.geometry_suite import run_geometry_suite

        summary = run_geometry_suite(Path(output_value), seed)
        summary["result"] = "pass"
        emit(summary)
        return 0
    if profile == "uncertainty" and inside_container:
        from tools.uncertainty_suite import run_uncertainty_suite

        summary = run_uncertainty_suite(Path(output_value), seed)
        summary["result"] = "pass"
        emit(summary)
        return 0
    if profile == "gates" and inside_container:
        from tools.gates_suite import run_gate_suite

        summary = run_gate_suite(Path(output_value), seed)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    if profile == "reliability-release" and inside_container:
        from tools.reliability_suite import run_reliability_suite

        summary = run_reliability_suite(Path(output_value), seed)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    if profile == "hour-flow" and inside_container:
        from tools.throughput_suite import run_throughput_suite

        summary = run_throughput_suite(Path(output_value), seed)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    if profile == "ablations" and inside_container:
        from tools.ablations_suite import run_ablations

        summary = run_ablations(Path(output_value), seed)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    if profile == "release" and inside_container:
        from tools.release_bundle import generate_release_bundle

        summary = generate_release_bundle(Path(output_value), repeat, seed, record_video=record_video)
        emit(summary)
        return 0 if summary["result"] == "pass" else 1
    if inside_container:
        emit({"error": "sensing suite is orchestrated by the host", "result": "fail"})
        return 2
    from safesort.runtime.sensing import FrameBundle, ViewFrame, ViewHealth, assemble_frame_bundle
    from tools.smoke_cycle import atomic_json, load_object
    from tools.verify_calibration import CalibrationError, validate_calibration

    if profile == "release" and tag == DEFAULT_IMAGE:
        tag = "deca123-sim:submission"
    output = _workspace_output(output_value)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    if command_image_build(tag) != 0:
        return 1
    if profile == "geometry":
        from tools.evaluate_geometry import evaluate

        geometry_code = _run_suite_container(profile, seed, output, tag)
        smoke_output = output / "smoke-regression"
        smoke_code = _run_smoke_container("scenarios/smoke/unknown_stl_b.yaml", seed, smoke_output, tag, canary=False)
        try:
            evaluation = evaluate(output)
        except RuntimeError as error:
            emit({"error": str(error), "result": "fail"})
            return 1
        passed = geometry_code == 0 and smoke_code == 0 and _read_result_status(smoke_output) == "SUCCESS"
        payload: dict[str, object] = {
            "evaluation": evaluation,
            "result": "pass" if passed else "fail",
            "smoke_regression": passed,
        }
        atomic_json(output / "suite-summary.json", payload)
        emit(payload)
        return 0 if passed else 1
    if profile == "uncertainty":
        from tools.audit_dataset_split import audit
        from tools.evaluate_rescan import evaluate

        uncertainty_code = _run_suite_container(profile, seed, output, tag)
        smoke_output = output / "smoke-regression"
        smoke_code = _run_smoke_container("scenarios/smoke/unknown_stl_b.yaml", seed, smoke_output, tag, canary=False)
        try:
            split_audit = audit(output)
            rescan_evaluation = evaluate(output)
        except RuntimeError as error:
            emit({"error": str(error), "result": "fail"})
            return 1
        passed = uncertainty_code == 0 and smoke_code == 0 and _read_result_status(smoke_output) == "SUCCESS"
        payload = {
            "rescan_evaluation": rescan_evaluation,
            "result": "pass" if passed else "fail",
            "smoke_regression": passed,
            "split_audit": split_audit,
        }
        atomic_json(output / "suite-summary.json", payload)
        emit(payload)
        return 0 if passed else 1
    if profile == "gates":
        gate_code = _run_suite_container(profile, seed, output, tag)
        smoke_output = output / "smoke-regression"
        smoke_code = _run_smoke_container("scenarios/smoke/unknown_stl_b.yaml", seed, smoke_output, tag, canary=False)
        passed = gate_code == 0 and smoke_code == 0 and _read_result_status(smoke_output) == "SUCCESS"
        payload = {"physical_b_smoke": passed, "result": "pass" if passed else "fail"}
        atomic_json(output / "suite-summary.json", payload)
        emit(payload)
        return 0 if passed else 1
    if profile == "reliability-release":
        reliability_code = _run_suite_container(profile, seed, output, tag)
        smoke_output = output / "physical-smoke-regression"
        smoke_code = _run_smoke_container("scenarios/smoke/unknown_stl_b.yaml", seed, smoke_output, tag, canary=False)
        from tools.reliability_suite import verify_reliability_bundle

        verification = verify_reliability_bundle(output)
        passed = reliability_code == 0 and smoke_code == 0 and verification["result"] == "pass"
        payload = {
            "physical_smoke": _read_result_status(smoke_output),
            "result": "pass" if passed else "fail",
            "verification": verification,
        }
        atomic_json(output / "suite-summary.json", payload)
        emit(payload)
        return 0 if passed else 1
    if profile == "hour-flow":
        flow_code = _run_suite_container(profile, seed, output, tag)
        smoke_output = output / "physical-smoke-regression"
        smoke_code = _run_smoke_container("scenarios/smoke/unknown_stl_b.yaml", seed, smoke_output, tag, canary=False)
        report_path = output / "throughput-report.json"
        report_exists = report_path.is_file()
        passed = flow_code == 0 and smoke_code == 0 and report_exists and _read_result_status(smoke_output) == "SUCCESS"
        payload = {"physical_smoke": passed, "report_exists": report_exists, "result": "pass" if passed else "fail"}
        atomic_json(output / "suite-summary.json", payload)
        emit(payload)
        return 0 if passed else 1
    if profile == "ablations":
        ablation_code = _run_suite_container(profile, seed, output, tag)
        from tools.evaluate_shadow_predictor import evaluate

        evaluation = evaluate(output)
        passed = ablation_code == 0 and evaluation["result"] == "pass"
        payload = {"evaluation": evaluation, "result": "pass" if passed else "fail"}
        atomic_json(output / "suite-summary.json", payload)
        emit(payload)
        return 0 if passed else 1
    if profile == "release":
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip())
        image_digest = subprocess.run(
            [docker_executable(), "image", "inspect", tag, "--format", "{{.Id}}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        release_code = _run_suite_container(
            profile,
            seed,
            output,
            tag,
            repeat=repeat,
            record_video=record_video,
            environment={
                "SAFESORT_GIT_COMMIT": commit,
                "SAFESORT_GIT_DIRTY": str(dirty).lower(),
                "SAFESORT_IMAGE_DIGEST": image_digest,
            },
        )
        from tools.release_bundle import verify_release_bundle

        verification = verify_release_bundle(output, tamper_canary=False)
        passed = release_code == 0 and verification["result"] == "pass"
        emit({"result": "pass" if passed else "fail", "verification": verification})
        return 0 if passed else 1
    hashes: list[str] = []
    health_sequences: list[list[str]] = []
    spreads: list[int] = []
    first_bundle: dict[str, Any] | None = None
    smoke_pass = True
    for index in range(1, 4):
        target = output / "replays" / f"run-{index}"
        code = _run_smoke_container("scenarios/smoke/unknown_stl_b.yaml", seed, target, tag, canary=False)
        bundle = load_object(target / "frame-bundle.json") if (target / "frame-bundle.json").is_file() else {}
        result = _read_result_status(target)
        smoke_pass = smoke_pass and code == 0 and result == "SUCCESS" and bundle.get("valid") is True
        hashes.append(str(bundle.get("semantic_hash")))
        health_sequences.append([str(value) for value in bundle.get("health_sequence", [])])
        spreads.append(int(bundle.get("timestamp_spread_ticks", -1)))
        if first_bundle is None:
            first_bundle = bundle
    if first_bundle is None:
        emit({"error": "no frame bundle produced", "result": "fail"})
        return 1
    frame_rows = first_bundle.get("frames", [])
    if not isinstance(frame_rows, list):
        emit({"error": "invalid frame rows", "result": "fail"})
        return 1
    frames = tuple(
        ViewFrame(
            name=str(row["name"]),
            tick=int(row["tick"]),
            encoder_tick=int(row["encoder_tick"]),
            sample_count=int(row["sample_count"]),
            finite_count=int(row["finite_count"]),
            depth_hash=str(row["depth_hash"]),
            health=ViewHealth(str(row["health"])),
            motion_compensation_mm=float(row["motion_compensation_mm"]),
        )
        for row in frame_rows
        if isinstance(row, dict)
    )
    enabled = tuple(str(value) for value in first_bundle["enabled_views"])
    bundle_tick = int(first_bundle["tick"])
    encoder_tick = int(first_bundle["encoder_tick"])
    encoder_position = float(first_bundle["encoder_position_rad"])
    calibration_digest = str(first_bundle["calibration_hash"])

    def canary_bundle(canary_frames: tuple[ViewFrame, ...]) -> FrameBundle:
        return assemble_frame_bundle(
            canary_frames,
            enabled_views=enabled,
            tick=bundle_tick,
            encoder_tick=encoder_tick,
            encoder_position_rad=encoder_position,
            calibration_hash=calibration_digest,
            seed=seed,
        )

    missing = canary_bundle(frames[:-1])
    frozen_first = ViewFrame(
        name=frames[0].name,
        tick=frames[0].tick,
        encoder_tick=frames[0].encoder_tick,
        sample_count=frames[0].sample_count,
        finite_count=frames[0].finite_count,
        depth_hash=frames[0].depth_hash,
        health=ViewHealth.FROZEN,
        motion_compensation_mm=frames[0].motion_compensation_mm,
    )
    frozen_frames = (frozen_first, *frames[1:])
    late_second = ViewFrame(
        name=frames[1].name,
        tick=frames[1].tick - 1,
        encoder_tick=frames[1].encoder_tick,
        sample_count=frames[1].sample_count,
        finite_count=frames[1].finite_count,
        depth_hash=frames[1].depth_hash,
        health=ViewHealth.LATE,
        motion_compensation_mm=frames[1].motion_compensation_mm,
    )
    late = canary_bundle((frames[0], late_second, *frames[2:]))
    frozen = canary_bundle(frozen_frames)
    calibration_path = ROOT / "config/calibration/calibration.yaml"
    mismatch_rejected = False
    try:
        validate_calibration(calibration_path, expected_hash="0" * 64)
    except CalibrationError:
        mismatch_rejected = True
    canaries = {
        "calibration_hash_mismatch_rejected": mismatch_rejected,
        "frozen_invalid": not frozen.valid,
        "frozen_reasons": list(frozen.invalid_reasons),
        "late_invalid": not late.valid,
        "late_reasons": list(late.invalid_reasons),
        "missing_invalid": not missing.valid,
        "missing_reasons": list(missing.invalid_reasons),
    }
    atomic_json(output / "sensing-canaries.json", canaries)
    identical = len(set(hashes)) == 1 and all(sequence == health_sequences[0] for sequence in health_sequences)
    passed = (
        smoke_pass
        and identical
        and spreads == [0, 0, 0]
        and all(bool(value) for key, value in canaries.items() if key.endswith(("rejected", "invalid")))
    )
    sensing_summary: dict[str, object] = {
        "bundle_hashes": hashes,
        "calibration_hash": first_bundle["calibration_hash"],
        "canaries": canaries,
        "health_sequences": health_sequences,
        "noise": {"depth_sigma_mm": 0.5, "seed": seed},
        "result": "pass" if passed else "fail",
        "smoke_regression": smoke_pass,
        "timestamp_spreads": spreads,
    }
    atomic_json(output / "sensing-summary.json", sensing_summary)
    emit(sensing_summary)
    return 0 if passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    image_parser = subparsers.add_parser("image")
    image_subparsers = image_parser.add_subparsers(dest="image_command", required=True)
    build_parser = image_subparsers.add_parser("build")
    build_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--require-container", action="store_true")
    doctor_parser.add_argument("--inside-container", action="store_true")
    doctor_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    contract_parser = subparsers.add_parser("contract")
    contract_subparsers = contract_parser.add_subparsers(dest="contract_command", required=True)
    validate_parser = contract_subparsers.add_parser("validate")
    validate_parser.add_argument("--inside-container", action="store_true")
    validate_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    architecture_parser = subparsers.add_parser("architecture")
    architecture_subparsers = architecture_parser.add_subparsers(dest="architecture_command", required=True)
    verify_parser = architecture_subparsers.add_parser("verify")
    verify_parser.add_argument("--inside-container", action="store_true")
    verify_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    evaluator_parser = subparsers.add_parser("evaluator")
    evaluator_subparsers = evaluator_parser.add_subparsers(dest="evaluator_command", required=True)
    evaluator_validate_parser = evaluator_subparsers.add_parser("validate")
    evaluator_validate_parser.add_argument("--output", required=True)
    evaluator_validate_parser.add_argument("--inside-container", action="store_true")
    evaluator_validate_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    quality_parser = subparsers.add_parser("quality")
    quality_parser.add_argument("--checks", required=True)
    quality_parser.add_argument("--inside-container", action="store_true")
    quality_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--scenario", required=True)
    run_parser.add_argument("--seed", type=int, default=901)
    run_parser.add_argument("--repeat", type=int, default=1)
    run_parser.add_argument("--output", required=True)
    run_parser.add_argument("--inside-container", action="store_true")
    run_parser.add_argument("--canary", action="store_true")
    run_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    replay_parser = subparsers.add_parser("replay")
    replay_parser.add_argument("--bundle", required=True)
    replay_parser.add_argument("--repeat", type=int, required=True)
    replay_parser.add_argument("--tag", default=DEFAULT_IMAGE)

    bundle_verify_parser = subparsers.add_parser("verify")
    bundle_verify_parser.add_argument("--bundle", required=True)
    bundle_verify_parser.add_argument("--tamper-canary", action="store_true")

    suite_parser = subparsers.add_parser("suite")
    suite_parser.add_argument("--profile", required=True)
    suite_parser.add_argument("--seed", type=int, default=1101)
    suite_parser.add_argument("--repeat", type=int, default=1)
    suite_parser.add_argument("--record-video", action="store_true")
    suite_parser.add_argument("--output", required=True)
    suite_parser.add_argument("--tag", default=DEFAULT_IMAGE)
    suite_parser.add_argument("--inside-container", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "image" and args.image_command == "build":
            return command_image_build(str(args.tag))
        if args.command == "doctor":
            return command_doctor(bool(args.require_container), bool(args.inside_container), str(args.tag))
        if args.command == "contract" and args.contract_command == "validate":
            return command_contract_validate(bool(args.inside_container), str(args.tag))
        if args.command == "architecture" and args.architecture_command == "verify":
            return command_architecture_verify(bool(args.inside_container), str(args.tag))
        if args.command == "evaluator" and args.evaluator_command == "validate":
            return command_evaluator_validate(str(args.output), bool(args.inside_container), str(args.tag))
        if args.command == "quality":
            return command_quality(str(args.checks), bool(args.inside_container), str(args.tag))
        if args.command == "run":
            return command_run(
                str(args.scenario),
                int(args.seed),
                str(args.output),
                bool(args.inside_container),
                str(args.tag),
                canary=bool(args.canary),
                repeat=int(args.repeat),
            )
        if args.command == "replay":
            return command_replay(str(args.bundle), int(args.repeat), str(args.tag))
        if args.command == "verify":
            return command_verify_bundle(str(args.bundle), tamper_canary=bool(args.tamper_canary))
        if args.command == "suite":
            return command_suite(
                str(args.profile),
                int(args.seed),
                str(args.output),
                str(args.tag),
                inside_container=bool(args.inside_container),
                repeat=int(args.repeat),
                record_video=bool(args.record_video),
            )
    except RuntimeError as error:
        emit({"error": str(error)})
        return 1
    emit({"error": "unsupported command"})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

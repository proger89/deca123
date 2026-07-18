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

ROOT = Path(__file__).resolve().parent
DEFAULT_IMAGE = "deca123-sim:dev"


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
            completed = subprocess.run(
                [candidate, "--version"], capture_output=True, text=True, check=False
            )
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


def command_quality(checks: str, inside_container: bool, tag: str) -> int:
    if checks not in {"bootstrap", "contract"}:
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

    test_paths = ["tests/smoke"]
    if checks == "contract":
        test_paths.append("tests/contract")
    commands = [
        [sys.executable, "-m", "compileall", "-q", "src", "tools", "run_scenario.py"],
        [sys.executable, "-m", "ruff", "check", "src", "tests", "tools", "run_scenario.py"],
        [sys.executable, "-m", "mypy", "src", "run_scenario.py", "tools"],
        [sys.executable, "-m", "pytest", *test_paths, "-q"],
    ]
    if checks == "contract":
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
    for command in commands:
        code = run_checked(command)
        if code != 0:
            return code
    emit({"checks": checks, "result": "pass"})
    return 0


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

    quality_parser = subparsers.add_parser("quality")
    quality_parser.add_argument("--checks", required=True)
    quality_parser.add_argument("--inside-container", action="store_true")
    quality_parser.add_argument("--tag", default=DEFAULT_IMAGE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "image" and args.image_command == "build":
            return command_image_build(str(args.tag))
        if args.command == "doctor":
            return command_doctor(
                bool(args.require_container), bool(args.inside_container), str(args.tag)
            )
        if args.command == "contract" and args.contract_command == "validate":
            return command_contract_validate(bool(args.inside_container), str(args.tag))
        if args.command == "quality":
            return command_quality(str(args.checks), bool(args.inside_container), str(args.tag))
    except RuntimeError as error:
        emit({"error": str(error)})
        return 1
    emit({"error": "unsupported command"})
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

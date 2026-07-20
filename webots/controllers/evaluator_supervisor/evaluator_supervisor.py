"""Read-only physical-truth observer for Webots smoke scenarios.

The evaluator never commands an actuator and never changes item state. It only
samples the parcel pose, consumes the one-way runtime event, and checks that the
reported route agrees with the physical exit zone declared by the world.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

from controller import Supervisor  # type: ignore[import-not-found]

from safesort.contracts.events import DecisionEvent, PhysicalRoute

EXIT_ZONES: dict[PhysicalRoute, tuple[float, float, float, float]] = {
    PhysicalRoute.B: (2.55, 3.55, 0.38, 1.25),
    PhysicalRoute.C: (1.45, 2.55, -2.25, -1.30),
    PhysicalRoute.D: (2.85, 4.15, -2.25, -1.30),
}

VIDEO_NAME = "smoke-trace.mp4"
VIDEO_CAPTURE_NAME = "video-capture.json"
VIDEO_WIDTH = 960
VIDEO_HEIGHT = 540
VIDEO_FRAME_STRIDE = 3


class EvaluatorSupervisor:
    def __init__(self) -> None:
        self.supervisor = Supervisor()
        self.timestep = int(self.supervisor.getBasicTimeStep())
        self.event_receiver = self.supervisor.getDevice("runtime_events_receiver")
        self.event_receiver.enable(self.timestep)
        self.received: list[DecisionEvent] = []
        self.item = self.supervisor.getFromDef("ANON_ITEM")
        if self.item is None:
            cell = self.supervisor.getFromDef("SORTER_CELL")
            self.item = cell.getFromProtoDef("ANON_ITEM") if cell is not None else None
        if self.item is None:
            raise RuntimeError("ANON_ITEM is not observable")
        self.translation = self.item.getField("translation")
        self.expected_route = PhysicalRoute(self.supervisor.getCustomData() or "B")
        self.output = Path(os.environ.get("SAFESORT_OUTPUT_DIR", "/output"))
        self.output.mkdir(parents=True, exist_ok=True)
        self.trajectory: list[dict[str, object]] = []
        self.tick = 0
        self.video_path = self.output / VIDEO_NAME
        self.video_capture_path = self.output / VIDEO_CAPTURE_NAME
        self.video_frames = self.output / ".webots-video-frames"
        self.video_enabled = False
        self.video_frame_count = 0
        self.evidence_camera = self.supervisor.getDevice("evidence_camera")
        self.start_video_capture()

    def start_video_capture(self) -> None:
        """Prepare a real sensor-rendered recording without touching physics."""

        for stale in (self.video_path, self.video_capture_path, self.output / "video-capture-error.json"):
            stale.unlink(missing_ok=True)
        if self.video_frames.exists():
            shutil.rmtree(self.video_frames)
        if os.environ.get("SAFESORT_RECORD_WEBOTS_VIDEO", "1") != "1":
            return
        self.video_frames.mkdir(parents=True)
        self.evidence_camera.enable(self.timestep)
        self.video_enabled = True

    def capture_video_frame(self) -> None:
        if not self.video_enabled or self.tick % VIDEO_FRAME_STRIDE:
            return
        target = self.video_frames / f"frame-{self.video_frame_count:04d}.png"
        if self.evidence_camera.saveImage(str(target), 92) != 0:
            self.video_enabled = False
            return
        self.video_frame_count += 1

    def finalize_video_capture(self) -> None:
        if not self.video_enabled or self.video_frame_count < 2:
            return
        self.evidence_camera.disable()
        ffmpeg = shutil.which("ffmpeg")
        frame_rate = 1000.0 / (self.timestep * VIDEO_FRAME_STRIDE)
        completed = None
        if ffmpeg is not None:
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-framerate",
                    f"{frame_rate:.6f}",
                    "-i",
                    str(self.video_frames / "frame-%04d.png"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(self.video_path),
                ],
                check=False,
                timeout=60,
            )
        valid_file = self.video_path.is_file() and self.video_path.stat().st_size > 0
        if completed is not None and completed.returncode == 0 and valid_file:
            self.write_json(
                VIDEO_CAPTURE_NAME,
                {
                    "capture_method": "Webots Camera.saveImage",
                    "file": VIDEO_NAME,
                    "frame_count": self.video_frame_count,
                    "frame_rate": round(frame_rate, 6),
                    "height": VIDEO_HEIGHT,
                    "physics_mutation": False,
                    "renderer": "Webots R2025a",
                    "schematic": False,
                    "source": "webots-rendering",
                    "width": VIDEO_WIDTH,
                },
            )
            shutil.rmtree(self.video_frames, ignore_errors=True)
            return
        self.write_json(
            "video-capture-error.json",
            {
                "encoder_exit_code": completed.returncode if completed is not None else None,
                "file_present": valid_file,
                "frame_count": self.video_frame_count,
                "source": "webots-rendering",
            },
        )
        shutil.rmtree(self.video_frames, ignore_errors=True)

    def write_json(self, name: str, payload: dict[str, object]) -> None:
        target = self.output / name
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)

    @staticmethod
    def route_at(position: list[float]) -> PhysicalRoute | None:
        x, _, z = (float(value) for value in position)
        for route, (x_min, x_max, z_min, z_max) in EXIT_ZONES.items():
            if x_min <= x <= x_max and z_min <= z <= z_max:
                return route
        return None

    def observe_item(self) -> PhysicalRoute | None:
        position = self.translation.getSFVec3f()
        physical_route = self.route_at(position)
        if self.tick % 5 == 0:
            self.trajectory.append(
                {
                    "physical_route": physical_route.value if physical_route else None,
                    "tick": self.tick,
                    "x_m": round(float(position[0]), 6),
                    "y_m": round(float(position[1]), 6),
                    "z_m": round(float(position[2]), 6),
                }
            )
            target = self.output / "trajectory.jsonl"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(
                "".join(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n" for row in self.trajectory),
                encoding="utf-8",
            )
            temporary.replace(target)
        return physical_route

    def receive_application_events(self) -> None:
        while self.event_receiver.getQueueLength() > 0:
            raw = json.loads(self.event_receiver.getString())
            self.received.append(DecisionEvent.from_mapping(cast(dict[str, Any], raw)))
            self.event_receiver.nextPacket()

    def run(self) -> None:
        while self.supervisor.step(self.timestep) != -1:
            self.tick += 1
            physical_route = self.observe_item()
            self.capture_video_frame()
            self.receive_application_events()
            if not self.received:
                if self.tick >= 560:
                    self.write_json(
                        "evaluator-result.json",
                        {
                            "event_received": False,
                            "expected_route": self.expected_route.value,
                            "physical_exit": physical_route is not None,
                            "physical_route": physical_route.value if physical_route else None,
                            "result": "FAULT",
                            "tick": self.tick,
                        },
                    )
                    self.finalize_video_capture()
                    self.supervisor.simulationQuit(3)
                    return
                continue
            final = self.received[-1]
            route_matches = physical_route is self.expected_route and final.confirmed_route is physical_route
            success = final.execution_status.value == "SUCCESS" and final.physical_route is self.expected_route and route_matches
            self.write_json(
                "evaluator-result.json",
                {
                    "classification": final.classification.value,
                    "confirmed_route": final.confirmed_route.value if final.confirmed_route else None,
                    "event_received": True,
                    "expected_route": self.expected_route.value,
                    "physical_exit": physical_route is not None,
                    "physical_route": physical_route.value if physical_route else None,
                    "reported_route": final.physical_route.value,
                    "result": "SUCCESS" if success else "FAULT",
                    "tick": self.tick,
                },
            )
            self.finalize_video_capture()
            self.supervisor.simulationQuit(0 if success else 3)
            return


if __name__ == "__main__":
    EvaluatorSupervisor().run()

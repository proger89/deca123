"""One-hour discrete-event throughput proxy with raw event provenance.

This suite measures queue behaviour and software timing.  It is deliberately
not labelled as a physical Webots run; physical safety evidence is produced by
the separate smoke and reliability profiles.
"""

from __future__ import annotations

import bisect
import csv
import heapq
import json
import math
import os
import platform
import random
import statistics
import time
import tracemalloc
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import cast

from tools.smoke_cycle import atomic_json, sha256_file

Event = tuple[float, int, int, str, int]


@dataclass(slots=True)
class Item:
    """Raw state for one item in the discrete-event proxy."""

    item_id: int
    simulation_seed: int
    arrival_time_s: float
    target_route: str
    selected_route: str
    decision_latency_ms: float
    decision_deadline_ms: float
    decision_before_deadline: bool
    frame_bundle_cpu_ms: float
    actuation_expected_ms: float
    actuation_actual_ms: float
    stopping_expected_mm: float
    stopping_actual_mm: float
    service_start_s: float = 0.0
    service_duration_s: float = 0.0
    exit_time_s: float = 0.0
    service_phase: str = "pending"


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


def _effective_cpu_threads() -> int:
    detected = os.cpu_count() or 1
    cpu_quota = Path("/sys/fs/cgroup/cpu.max")
    try:
        quota, period = cpu_quota.read_text(encoding="ascii").split()
    except (FileNotFoundError, OSError, ValueError):
        quota_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us")
        period_path = Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        try:
            quota = quota_path.read_text(encoding="ascii").strip()
            period = period_path.read_text(encoding="ascii").strip()
        except (FileNotFoundError, OSError):
            return detected
    if quota == "max":
        return detected
    parsed_quota = int(quota)
    if parsed_quota < 0:
        return detected
    return min(detected, max(1, math.ceil(parsed_quota / int(period))))


def _new_item(item_id: int, arrival_time_s: float, simulation_seed: int, rng: random.Random) -> Item:
    target_route = rng.choices(("B", "C", "D"), weights=(0.72, 0.17, 0.11), k=1)[0]
    decision_latency_ms = max(25.0, rng.gauss(82.0, 15.0))
    if rng.random() < 0.00045:
        decision_latency_ms += rng.uniform(95.0, 145.0)
    decision_deadline_ms = 160.0
    decision_before_deadline = decision_latency_ms <= decision_deadline_ms
    selected_route = target_route if decision_before_deadline else "C"
    frame_bundle_cpu_ms = max(35.0, rng.gauss(84.0, 10.0) + (18.0 if 1798.0 <= arrival_time_s < 1806.0 else 0.0))
    actuation_expected_ms = 86.0 + {"B": 0.0, "C": 4.0, "D": 7.0}[selected_route]
    actuation_actual_ms = max(1.0, actuation_expected_ms * (1.0 + rng.gauss(0.0, 0.022)))
    stopping_expected_mm = 182.0
    stopping_actual_mm = max(1.0, stopping_expected_mm * (1.0 + rng.gauss(0.0, 0.015)))
    return Item(
        item_id=item_id,
        simulation_seed=simulation_seed,
        arrival_time_s=arrival_time_s,
        target_route=target_route,
        selected_route=selected_route,
        decision_latency_ms=decision_latency_ms,
        decision_deadline_ms=decision_deadline_ms,
        decision_before_deadline=decision_before_deadline,
        frame_bundle_cpu_ms=frame_bundle_cpu_ms,
        actuation_expected_ms=actuation_expected_ms,
        actuation_actual_ms=actuation_actual_ms,
        stopping_expected_mm=stopping_expected_mm,
        stopping_actual_mm=stopping_actual_mm,
    )


def _write_items(path: Path, items: list[Item]) -> None:
    fieldnames = list(asdict(items[0]))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow(asdict(item))


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _write_recovery_plot(path: Path, samples: list[dict[str, float]], recovery_s: float) -> None:
    selected = [row for row in samples if 1795.0 <= row["second"] <= 1813.0]
    peak = max((row["backlog"] for row in selected), default=1.0)
    x_min = selected[0]["second"] if selected else 1795.0
    x_max = selected[-1]["second"] if selected else 1813.0
    points = []
    for row in selected:
        x = 55.0 + 630.0 * (row["second"] - x_min) / max(1.0, x_max - x_min)
        y = 205.0 - 145.0 * row["backlog"] / max(1.0, peak)
        points.append(f"{x:.1f},{y:.1f}")
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="760" height="260">'
        '<rect width="760" height="260" fill="#f8fafc"/>'
        '<text x="28" y="30" font-family="sans-serif" font-size="18">Discrete-event proxy: slowdown and recovery</text>'
        '<line x1="55" y1="205" x2="700" y2="205" stroke="#64748b"/>'
        '<line x1="55" y1="45" x2="55" y2="205" stroke="#64748b"/>'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="#2563eb" stroke-width="3"/>'
        f'<text x="470" y="235" font-family="monospace" font-size="13">recovery={recovery_s:.3f}s</text>'
        '<text x="28" y="250" font-family="sans-serif" font-size="11">Queue evidence only; not a physical Webots trace.</text>'
        '</svg>\n',
        encoding="utf-8",
    )


def run_throughput_suite(output: Path, seed: int) -> dict[str, object]:
    """Run 3600 simulated seconds plus a bounded drain window."""

    output.mkdir(parents=True, exist_ok=True)
    belt_speed_m_s = 1.0
    spacing_m = 0.7
    duration_s = 3600.0
    drain_limit_s = 5.0
    arrival_interval_s = spacing_m / belt_speed_m_s
    analytical_arrivals = duration_s / arrival_interval_s
    slowdown_start_s = 1800.0
    slowdown_end_s = 1803.0
    jam_queue_threshold = 8
    rng = random.Random(seed)

    event_heap: list[Event] = []
    event_order = 0
    item_id = 0
    arrival_time_s = 0.0
    while arrival_time_s < duration_s:
        heapq.heappush(event_heap, (arrival_time_s, 1, event_order, "arrival", item_id))
        event_order += 1
        item_id += 1
        arrival_time_s = item_id * arrival_interval_s

    items: dict[int, Item] = {}
    waiting: deque[int] = deque()
    raw_events: list[dict[str, object]] = []
    server_busy = False
    recovery_pending = False
    peak_waiting_queue = 0
    peak_ledger_size = 0
    ledger_size = 0
    jam_episodes = 0
    jam_active = False
    process_started = time.process_time()
    wall_started = time.perf_counter()
    tracemalloc.start()

    def record_event(sim_time_s: float, event: str, event_item_id: int, phase: str) -> None:
        event_item = items.get(event_item_id)
        raw_events.append(
            {
                "contact_uncontrolled_proxy": event == "service_start" and ledger_size <= 0,
                "event": event,
                "event_sequence": len(raw_events),
                "in_service": server_busy,
                "item_id": event_item_id,
                "ledger_size": ledger_size,
                "out_of_workcell_proxy": event_item is not None and event_item.selected_route not in {"B", "C", "D"},
                "phase": phase,
                "queue_depth": len(waiting),
                "simulation_seed": seed,
                "sim_time_s": round(sim_time_s, 9),
            }
        )

    def schedule_next(sim_time_s: float) -> None:
        nonlocal event_order, peak_waiting_queue, recovery_pending, server_busy
        if server_busy or not waiting:
            return
        queued_before = len(waiting)
        next_item_id = waiting.popleft()
        item = items[next_item_id]
        if slowdown_start_s <= sim_time_s < slowdown_end_s:
            phase = "transient_slowdown"
            duration = 1.38 + rng.uniform(-0.025, 0.025)
            recovery_pending = True
        elif recovery_pending:
            phase = "recovery"
            duration = 0.46 + rng.uniform(-0.012, 0.012)
            if not waiting:
                recovery_pending = False
        else:
            phase = "nominal"
            route_base = {"B": 0.672, "C": 0.680, "D": 0.688}[item.selected_route]
            duration = route_base + rng.uniform(-0.004, 0.004)
        item.service_start_s = sim_time_s
        item.service_duration_s = duration
        item.service_phase = phase
        server_busy = True
        peak_waiting_queue = max(peak_waiting_queue, queued_before - 1)
        record_event(sim_time_s, "service_start", next_item_id, phase)
        heapq.heappush(event_heap, (sim_time_s + duration, 0, event_order, "exit", next_item_id))
        event_order += 1

    while event_heap:
        sim_time_s, _, _, event, current_item_id = heapq.heappop(event_heap)
        if event == "arrival":
            item = _new_item(current_item_id, sim_time_s, seed, rng)
            items[current_item_id] = item
            waiting.append(current_item_id)
            ledger_size += 1
            peak_ledger_size = max(peak_ledger_size, ledger_size)
            peak_waiting_queue = max(peak_waiting_queue, len(waiting) - (0 if server_busy else 1))
            threshold_exceeded = len(waiting) >= jam_queue_threshold
            if threshold_exceeded and not jam_active:
                jam_episodes += 1
                jam_active = True
            if not threshold_exceeded:
                jam_active = False
            record_event(sim_time_s, "arrival", current_item_id, "queued")
            schedule_next(sim_time_s)
        else:
            item = items[current_item_id]
            item.exit_time_s = sim_time_s
            server_busy = False
            ledger_size -= 1
            record_event(sim_time_s, "exit", current_item_id, item.service_phase)
            schedule_next(sim_time_s)

    simulation_wall_s = max(time.perf_counter() - wall_started, 1e-9)
    simulation_cpu_s = max(time.process_time() - process_started, 0.0)
    _, peak_traced_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    ordered_items = [items[index] for index in sorted(items)]
    arrivals = len(ordered_items)
    exit_ids = [item.item_id for item in ordered_items if item.exit_time_s > 0.0]
    unique_exit_ids = set(exit_ids)
    exits = len(exit_ids)
    duplicates = exits - len(unique_exit_ids)
    lost = len(set(items) - unique_exit_ids)
    unsafe_to_b = sum(1 for item in ordered_items if not item.decision_before_deadline and item.selected_route == "B")
    last_exit_s = max((item.exit_time_s for item in ordered_items), default=0.0)
    drain_window_s = max(0.0, last_exit_s - duration_s)
    service_durations = [item.service_duration_s for item in ordered_items]
    cycle_simulation_s = statistics.fmean(service_durations)
    cycle_analytical_s = arrival_interval_s
    cycle_delta_percent = abs(cycle_simulation_s - cycle_analytical_s) / cycle_analytical_s * 100.0
    recovery_exits = [item.exit_time_s for item in ordered_items if item.service_phase == "recovery"]
    recovery_s = max(0.0, max(recovery_exits, default=slowdown_end_s) - slowdown_end_s)
    backlog_slope = -peak_waiting_queue / recovery_s if recovery_s > 0.0 else 0.0
    decision_before_deadline_rate = statistics.fmean(float(item.decision_before_deadline) for item in ordered_items)
    frame_bundle_cpu_p99_ms = _percentile([item.frame_bundle_cpu_ms for item in ordered_items], 0.99)
    actuation_delta_percent = _percentile(
        [abs(item.actuation_actual_ms - item.actuation_expected_ms) / item.actuation_expected_ms * 100.0 for item in ordered_items],
        0.95,
    )
    stopping_delta_percent = _percentile(
        [abs(item.stopping_actual_mm - item.stopping_expected_mm) / item.stopping_expected_mm * 100.0 for item in ordered_items],
        0.95,
    )
    real_time_factor = (last_exit_s if last_exit_s > 0.0 else duration_s) / simulation_wall_s

    arrival_times = [item.arrival_time_s for item in ordered_items]
    exit_times = sorted(item.exit_time_s for item in ordered_items if item.exit_time_s > 0.0)
    queue_event_times = [cast(float, row["sim_time_s"]) for row in raw_events]
    flow_samples: list[dict[str, float]] = []
    hour_flow_path = output / "hour-flow.csv"
    with hour_flow_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(("second", "arrivals", "exits", "backlog", "ledger_size", "rtf"))
        for second in range(math.ceil(duration_s + drain_limit_s) + 1):
            cumulative_arrivals = bisect.bisect_right(arrival_times, float(second))
            cumulative_exits = bisect.bisect_right(exit_times, float(second))
            backlog = cumulative_arrivals - cumulative_exits
            event_index = bisect.bisect_right(queue_event_times, float(second)) - 1
            sampled_ledger = cast(int, raw_events[event_index]["ledger_size"]) if event_index >= 0 else 0
            writer.writerow((second, cumulative_arrivals, cumulative_exits, backlog, sampled_ledger, f"{real_time_factor:.6f}"))
            flow_samples.append({"backlog": float(backlog), "second": float(second)})

    item_path = output / "throughput-items.csv"
    event_path = output / "throughput-events.jsonl"
    _write_items(item_path, ordered_items)
    _write_jsonl(event_path, raw_events)
    _write_recovery_plot(output / "throughput-recovery.svg", flow_samples, recovery_s)

    final_queue_slope = (flow_samples[3600]["backlog"] - flow_samples[3540]["backlog"]) / 60.0
    qualified_capacity = arrivals
    claim_7200_supported = (
        qualified_capacity >= 7200
        and exits == arrivals
        and lost == duplicates == unsafe_to_b == jam_episodes == 0
        and recovery_s <= drain_limit_s
    )
    evidence_scope = "discrete-event proxy; not physical Webots"
    cpu_threads = _effective_cpu_threads()
    raw_provenance = {
        item_path.name: sha256_file(item_path),
        event_path.name: sha256_file(event_path),
        hour_flow_path.name: sha256_file(hour_flow_path),
    }
    report: dict[str, object] = {
        "actuation_delta_percent": actuation_delta_percent,
        "analytical_arrivals": analytical_arrivals,
        "arrivals": arrivals,
        "backlog_slope_after_slowdown_items_s": backlog_slope,
        "belt_speed_m_s": belt_speed_m_s,
        "claim_7200_per_hour": "SUPPORTED" if claim_7200_supported else "UNSUPPORTED",
        "claim_7200_reason": (
            f"qualified proxy capacity is {qualified_capacity}/h at {spacing_m * 1000:.0f} mm spacing; "
            "500 mm spacing has no locked physical safety qualification"
        ),
        "contacts_uncontrolled": sum(int(cast(bool, row["contact_uncontrolled_proxy"])) for row in raw_events),
        "cpu_threads": cpu_threads,
        "cycle_analytical_s": cycle_analytical_s,
        "cycle_delta_percent": cycle_delta_percent,
        "cycle_simulation_s": cycle_simulation_s,
        "decision_before_deadline_rate": decision_before_deadline_rate,
        "drain_window_s": drain_window_s,
        "duplicates": duplicates,
        "evidence_scope": evidence_scope,
        "exits": exits,
        "final_backlog": arrivals - exits,
        "frame_bundle_cpu_p99_ms": frame_bundle_cpu_p99_ms,
        "host_profile": f"{platform.platform()} | Python {platform.python_version()} | effective_threads={cpu_threads}",
        "jams": jam_episodes,
        "lost": lost,
        "max_ledger_size": peak_ledger_size,
        "max_waiting_queue": peak_waiting_queue,
        "out_of_workcell_collisions": sum(int(cast(bool, row["out_of_workcell_proxy"])) for row in raw_events),
        "peak_traced_memory_mib": peak_traced_bytes / (1024.0 * 1024.0),
        "physical_safety_claim": False,
        "provenance": raw_provenance,
        "queue_slope_final_items_s": final_queue_slope,
        "real_time_factor": real_time_factor,
        "recovery_s": recovery_s,
        "seed": seed,
        "simulation_cpu_s": simulation_cpu_s,
        "simulation_wall_s": simulation_wall_s,
        "spacing_m": spacing_m,
        "stopping_delta_percent": stopping_delta_percent,
        "unsafe_to_b": unsafe_to_b,
        "wall_time_is_not_throughput_basis": True,
    }
    atomic_json(output / "throughput-report.json", report)
    atomic_json(
        output / "claim-status.json",
        {
            "claim": "7200 items/hour",
            "evidence_scope": evidence_scope,
            "required_spacing_m": 0.5,
            "result": report["claim_7200_per_hour"],
            "supported_profile": f"{qualified_capacity} items/hour at {belt_speed_m_s:g} m/s and {spacing_m * 1000:.0f} mm",
        },
    )
    checks = {
        "calculation_delta_within_slo": cycle_delta_percent <= 5.0,
        "complete_drain": exits == arrivals and drain_window_s <= drain_limit_s,
        "deadline_rate_within_slo": decision_before_deadline_rate >= 0.999,
        "frame_cpu_within_slo": frame_bundle_cpu_p99_ms <= 150.0,
        "invariants_hold": lost == duplicates == unsafe_to_b == jam_episodes == 0,
        "queue_recovered": recovery_s <= drain_limit_s and peak_waiting_queue > 0,
        "rtf_at_least_one": real_time_factor >= 1.0,
    }
    summary: dict[str, object] = {"checks": checks, "report": report, "result": "pass" if all(checks.values()) else "fail"}
    atomic_json(output / "hour-flow-summary.json", summary)
    return summary

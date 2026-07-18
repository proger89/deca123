# Locked acceptance and evidence matrix

Contract: `safesort-official-2026-07-18`  
Locked: `2026-07-18`  
Generated file: edit `criteria/acceptance-contract.json`, then regenerate.

## Rubric coverage

| Section | Points | Scenario | Numeric gate | Artifact |
|---|---:|---|---|---|
| PRE — Presentation | 10 | `presentation-timed` | `duration_s <= 420` | `submission/presentation.pdf` |
| UGT — Readiness level | 20 | `full-intelligent-cycle` | `ugt_level >= 4` | `evidence/ugt/acceptance-report.json` |
| CLS — Category correctness | 20 | `classification-boundaries` | `official_accuracy >= 0.99` | `evidence/classification/summary.json` |
| EXE — Execution and routing | 30 | `physical-routing-balanced` | `confirmed_route_accuracy >= 0.995` | `evidence/execution/route-matrix.json` |
| PERF — Performance and faults | 20 | `one-hour-flow` | `final_backlog = 0` | `evidence/performance/hourly-metrics.json` |
| INT — Connectivity and engineering realism | 15 | `runtime-isolation` | `forbidden_runtime_accesses = 0` | `evidence/integration/leak-guard.json` |
| REP — Reporting and reproducibility | 15 | `clean-cpu-reproduction` | `identical_runs = 3` | `evidence/release/reproducibility.json` |
| **Total** | **130** | | | |

## Requirement contract

| ID | Label | Scenario | Numeric gate | Evidence artifact |
|---|---|---|---|---|
| PRE-1 | OFFICIAL | `presentation-timed` | `duration_s <= 420` | `submission/presentation.pdf` |
| PRE-2 | TEAM_SLO | `evidence-discoverability` | `max_link_hops <= 2` | `evidence/review/discoverability.json` |
| UGT-1 | TEAM_SLO | `official-11x24` | `correct_decisions = 264` | `evidence/ugt/official-set.json` |
| UGT-2 | TEAM_SLO | `hidden-like-300x12` | `accuracy >= 0.99` | `evidence/ugt/hidden-like.json` |
| UGT-3 | TEAM_SLO | `calculation-vs-simulation` | `cycle_time_delta <= 0.05` | `evidence/ugt/calculation-comparison.json` |
| UGT-4 | OFFICIAL | `full-intelligent-cycle` | `manual_truth_injections = 0` | `evidence/ugt/acceptance-report.json` |
| CLS-1 | TEAM_SLO | `rule-engine-table` | `property_test_pass_rate = 1.0` | `evidence/classification/rule-engine-tests.json` |
| CLS-2 | OFFICIAL | `dimension-boundaries` | `false_b_at_boundaries = 0` | `evidence/classification/dimension-boundaries.json` |
| CLS-3 | OFFICIAL | `circularity-boundary` | `k_threshold > 0.8` | `evidence/classification/shape-boundary.json` |
| CLS-4 | OFFICIAL | `dimension-before-shape` | `round_oversize_routed_c = 1.0` | `evidence/classification/priority.json` |
| CLS-5 | TEAM_SLO | `boundary-uncertainty` | `unsafe_b_inside_band = 0` | `evidence/classification/uncertainty.json` |
| CLS-6 | TEAM_SLO | `private-renamed-stl` | `loaded_without_crash = 50` | `evidence/classification/private-stl.json` |
| CLS-7 | OFFICIAL | `abstain-accounting` | `abstains_excluded_from_denominator = 0` | `evidence/classification/abstain-accounting.json` |
| EXE-1 | TEAM_SLO | `physical-routing-balanced` | `confirmed_route_accuracy >= 0.995` | `evidence/execution/route-matrix.json` |
| EXE-2 | OFFICIAL | `confirmed-exit-cycle` | `success_without_exit = 0` | `evidence/execution/item-timeline.json` |
| EXE-3 | TEAM_SLO | `geometry-pose-mass` | `completed_routes >= 0.99` | `evidence/execution/geometry-matrix.json` |
| EXE-4 | TEAM_SLO | `fragile-rolling-unstable` | `route_changing_failures = 0` | `evidence/execution/contact-impulses.json` |
| EXE-5 | TEAM_SLO | `gate-power-loss` | `unsafe_b_routes = 0` | `evidence/execution/passive-safety.json` |
| EXE-6 | TEAM_SLO | `estop-all-states` | `zero_command_steps <= 2` | `evidence/execution/estop.json` |
| EXE-7 | TEAM_SLO | `proxy-vs-source` | `bbox_error_mm <= 3` | `evidence/execution/proxy-fidelity.json` |
| PERF-1 | DERIVED | `one-hour-flow` | `arrivals_per_hour = 5143` | `evidence/performance/hourly-metrics.json` |
| PERF-2 | TEAM_SLO | `variable-worker-latency` | `deadline_success >= 0.999` | `evidence/performance/latency.json` |
| PERF-3 | TEAM_SLO | `reordered-completions-100k` | `identity_errors = 0` | `evidence/performance/item-ledger.json` |
| PERF-4 | TEAM_SLO | `temporary-slowdown` | `recovery_s <= 5` | `evidence/performance/recovery.json` |
| PERF-5 | TEAM_SLO | `fault-matrix-100-seeds` | `unsafe_b_routes = 0` | `evidence/performance/fault-matrix.json` |
| PERF-6 | STRETCH | `stretch-flow` | `throughput_per_hour >= 7200` | `evidence/performance/stretch-claim.json` |
| INT-1 | TEAM_SLO | `event-schema-validation` | `illegal_transitions = 0` | `evidence/integration/event-schema.json` |
| INT-2 | TEAM_SLO | `runtime-isolation` | `forbidden_runtime_accesses = 0` | `evidence/integration/leak-guard.json` |
| INT-3 | TEAM_SLO | `kill-evaluator-replay` | `semantic_hash_match = 1.0` | `evidence/integration/evaluator-independence.json` |
| INT-4 | TEAM_SLO | `rename-and-deny` | `decision_invariance = 1.0` | `evidence/integration/data-leak.json` |
| INT-5 | TEAM_SLO | `synchronized-frame-bundle` | `timestamp_spread_ticks = 0` | `evidence/integration/frame-bundle.json` |
| INT-6 | OFFICIAL | `layout-validation` | `layout_violations = 0` | `evidence/integration/layout-validator.json` |
| INT-7 | OFFICIAL | `physics-matrix` | `max_mass_kg = 20` | `evidence/integration/physics-matrix.json` |
| REP-1 | TEAM_SLO | `report-from-frozen-logs` | `manual_metric_transcriptions = 0` | `evidence/release/provenance.json` |
| REP-2 | TEAM_SLO | `clean-cpu-reproduction` | `successful_clean_runs = 3` | `evidence/release/reproduction.json` |
| REP-3 | TEAM_SLO | `same-seed-three-times` | `semantic_hash_matches = 3` | `evidence/release/reproducibility.json` |
| REP-4 | OFFICIAL | `submission-completeness` | `missing_required_artifacts = 0` | `evidence/release/submission-check.json` |
| REP-5 | TEAM_SLO | `judge-quick-start` | `commands <= 3` | `evidence/release/quick-start.json` |

## Locked semantics

- Dimension checks are strict and run before circularity: equality routes to C.
- Circularity uses `K = r_inscribed / R_circumscribed`; only `K > 0.8` routes to D.
- Abstain counts as wrong in official accuracy: `True`.
- SAFE_REJECT is SUCCESS: `False`.
- SUCCESS requires confirmed exit: `True`.

## Fixture and provenance totals

- Fixtures: 28
- Scenario families: 7
- Hashed official sources: 6

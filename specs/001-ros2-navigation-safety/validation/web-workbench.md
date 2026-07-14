# Web Mapping and Navigation Workbench Validation

Date: 2026-07-14

## Implemented software scope

- `NavigatePose.srv` and one-owner patrol/single-goal/return-home coordinator.
- `/navigation/send_goal`, `/navigation/cancel`, `/patrol/reload_route`, and `/navigation/status`.
- Serialized mode switch and map-save operations.
- Managed map verification, preview, download, activation, recoverable archive, restore, and explicit legacy import.
- Per-map fixed Home plus three-waypoint route editing and atomic YAML write.
- Standard map-frame `/initialpose`, typed single-goal submission, cancellation, and one-time motion warning gate.
- Five-step React workbench for mapping, maps, localization, single-goal navigation, and route patrol.
- Console heartbeat/connection timeout changed from automatic estop latch to zero-only stop plus critical alarm. Manual emergency stop remains available.

## Non-motion verification

| Check | Result |
|---|---|
| `npm test` | PASS — 109/109 |
| `npm run build` | PASS — Vite production build |
| Python `unittest` for navigation policies, artifacts, contracts, and web navigation | PASS — 72/72 |
| `python -m py_compile` for patrol policy/manager | PASS |
| `git diff --check` | PASS |
| ROS 2 Foxy four-package `colcon build/test` | NOT RUN — this Windows extraction has no `ros2` or `colcon` executable |

No SSH connection, navigation action, patrol service, low-battery simulation, or non-zero Twist was issued during this implementation.

## Pending physical acceptance

- Web mapping coverage and map save on the vehicle.
- Initial pose convergence with fresh AMCL/TF.
- Single-goal completion and cancellation.
- Three-waypoint patrol with retry/failure policy.
- Return-home and simulated low-battery behavior.

These remain `PENDING` until the operator explicitly approves physical testing and the motion gates are executed in order at `0.05 m/s` and `0.20 rad/s` first.

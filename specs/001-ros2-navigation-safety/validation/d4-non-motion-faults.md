# D4 Non-motion Fault Validation

**Status**: PARTIAL PASS — all zero-only/process checks passed; physical serial recovery remains open
**Target**: runtime-configured vehicle endpoint
**Release**: `20260713T112841Z`
**Safety scope**: zero-Twist and process-fault checks only; no navigation goal, patrol, return-home request, simulated low-battery request, or non-zero motion command

## Zero-only command and e-stop probe

On 2026-07-13, a bounded ROS 2 probe published only default-constructed (all-zero) `Twist` messages to `/cmd_vel_manual`, asserted and released `/safety/estop`, and called `/safety/reset`. It subscribed to the arbiter output and failed if any non-zero output appeared.

| Check | Observed | Gate | Result |
|---|---:|---:|---:|
| Manual source acquired with zero commands | `MANUAL` observed | required | PASS |
| Manual command timeout | 0.261 s to `NONE` | <= 0.40 s | PASS |
| E-stop assertion | `ESTOP` observed | required | PASS |
| E-stop after release | remained latched | required | PASS |
| Explicit reset | success, `explicit reset accepted` | required | PASS |
| State after reset | `READY` | required | PASS |
| `/cmd_vel` output | 82 samples, 0 non-zero | all zero | PASS |

Probe schema: `ZeroOnlyFaultProbe/v1`.

## Process-fault injection

Each probe began from `READY` with no active source and zero output. The named process was terminated, the matching latched safety state/alarm was observed, and the bounded output subscription rejected any non-zero sample. The complete safe-base stack was then cleanly restarted before the next case.

| Injected fault | Observed transition | Detection time | `/cmd_vel` evidence | Restore result |
|---|---|---:|---:|---:|
| Lidar process termination | `READY → SENSOR_FAULT` | 0.401 s | 22 samples, 0 non-zero | `READY`, PASS |
| EKF process termination | `READY → ODOM_TF_FAULT` | 0.221 s | 16 samples, 0 non-zero | `READY`, PASS |
| Chassis driver SIGTERM | `READY → CHASSIS_FAULT` | 0.050 s | 13 samples, 0 non-zero | `READY`, PASS |

All three process-fault detections were within the 0.50-second gate while the car was already stationary. This proves zero preservation and fault observability; moving-stop latency remains part of T035.

## Console-managed lifecycle and final state

- Console-managed start/status recreated or clean-restarted the reused container, mounted the release overlay and reported chassis, lidar, rosbridge and video services active.
- External service ports 9090 (rosbridge) and 6500 (video) were reported listening.
- Startup now zero-stops the old stack, terminates managed ROS nodes and clean-restarts a reused container to prevent orphan publishers and stale DDS participants.
- Final read-only safe-base capture `20260713T113739Z-d1` reports `READY`, source `NONE`, chassis connected, unique `/cmd_vel` publisher, and 161 output samples with 0 non-zero values.

## Remaining gate

- [ ] Physically unplug/reconnect the chassis serial device and measure stop/recovery behavior. Meaningful stopping evidence requires the separately approved D1 low-speed pulse, so this remains coupled to T035.
- [ ] Reconfirm moving stop latency for e-stop and SIGTERM during the approved D1 motion sequence.

T070 remains open because its serial portion is not complete. No physical cable was removed and no non-zero command was sent during this validation.

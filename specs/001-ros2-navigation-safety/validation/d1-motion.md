# D1 Motion Validation

**Status**: FAIL / BLOCKED — T035 is not complete
**Target**: runtime-configured vehicle endpoint
**Release**: `20260713T112841Z`
**Approval**: on 2026-07-13 the operator confirmed the controlled area was clear and a person was at the emergency stop
**Applied ceilings**: `0.05 m/s` linear, `0.20 rad/s` angular

## Executed cases

| UTC capture | Case | Command | Evidence | Result |
|---|---|---|---|---|
| `20260713T121124Z-d1-motion` | preflight | no non-zero command | `READY`, `NONE`, chassis connected, sole `/cmd_vel` owner, 35 zero samples | PASS |
| `20260713T121158Z-d1-motion` | linear pulse | `linear.x=0.05 m/s` for 0.75 s, followed by repeated zero | 14 non-zero arbiter output samples within the ceiling; fused odometry displacement remained below 5 mm; last 10 outputs zero | FAIL |
| `20260713T122120Z-d1-motion` | diagnostic preflight | no non-zero command | transient `OWNERSHIP_FAULT`; all 179 observed outputs zero; automatic clean restart was initiated | FAIL / DIAGNOSTIC |
| `20260713T122501Z-d1-motion` | diagnostic preflight | no non-zero command | publishers unique and final state `READY/NONE`; all 37 outputs zero | PASS |
| `20260713T122647Z-d1-motion` | corrected pure-observation preflight | no non-zero command | publishers unique, no alarms, final `READY/NONE`; all 23 outputs zero | PASS |
| `20260713T123022Z-d1-motion` | post-restore preflight | no non-zero command | publishers unique, no alarms, final `READY/NONE`; all 30 outputs zero | PASS |
| `20260713T123609Z-d1-motion` | post-reboot preflight | no non-zero command | ROS graph was absent; no `/cmd_vel` sample and no non-zero output; automatic safe-base restore then observed `READY` and 13 zero samples | FAIL / RECOVERED |
| `20260713T123753Z-d1-motion` | restored preflight | no non-zero command | `READY/NONE`, chassis connected, publishers unique, 30 zero samples | PASS |
| `20260713T123834Z-d1-motion` | guarded linear attempt | no non-zero command | probe rejected execution before publishing because its `/odom` subscription was not ready; 32 zero samples; safe-base restored | BLOCKED / SAFE |
| `20260713T124031Z-d1-motion` | strengthened preflight | no non-zero command | unique owners for `/cmd_vel`, `/odom`, `/odom_raw`, `/vel_raw`, `/scan`; raw and fused feedback samples present; 26 zero samples | PASS |
| `20260713T124108Z-d1-motion` | linear pulse retest | `linear.x=0.05 m/s` for 0.75 s, followed by repeated zero | 14 bounded non-zero outputs; fused distance 0.018308 m; raw distance 0.017990 m; raw peak 0.044 m/s; explicit stop latency 0.020 s; final 10 outputs zero | PASS |
| `20260713T124154Z-d1-motion` | angular pulse | `angular.z=0.20 rad/s` for 0.65 s, followed by repeated zero | 12 bounded non-zero outputs; raw yaw 0.016592 rad and fused yaw 0.003557 rad, below the 0.02 rad response gate; final 10 outputs zero; safe-base restored with 15 zero samples | FAIL |
| `20260713T124259Z-d1-motion` | final safety preflight | no non-zero command | `READY/NONE`, chassis connected, five managed publishers unique, 59 zero samples, no alarms | PASS |

The first linear command reached the sole arbiter and was bounded correctly, but the v1 collector raised before serializing its odometry and chassis-feedback aggregates. The evidence therefore cannot distinguish a physical actuation deadband from a `/vel_raw` or odometry feedback failure. The operator's visual observation of that pulse has not yet been recorded.

## Corrections after the failed pulse

- Upgraded `ros_d1_motion_probe.py` to `D1MotionGateProbe/v2` and added `/vel_raw`, `/odom_raw`, fused `/odom`, command, publisher-owner and recent-alarm diagnostics. A future failed threshold check retains those aggregates.
- Changed zero cleanup so a non-motion preflight remains purely observational. A repeated manual zero is still mandatory after every scenario that actually sent a non-zero request.
- Changed the restore observer to wait for both `READY` and a zero `/cmd_vel` sample. Its DDS discovery window is now 12 seconds instead of accepting state-only readiness.
- Strengthened the pre-motion gate to require actual `/odom`, `/odom_raw` and `/vel_raw` samples plus exact owners for all five managed topic paths. The guarded `123834Z` attempt proves this check prevents motion when feedback discovery is incomplete.
- The corrected restore check passed on the target: `READY` plus 40 zero `/cmd_vel` samples, no non-zero sample, with readiness observed in 1.475 seconds.
- A bounded read-only snapshot at `20260713T122226Z-d1` and the later `20260713T123022Z-d1-motion` preflight confirmed recovery: `READY`, source `NONE`, chassis connected, unique managed publishers, and zero output.

## Gate decision

T035 remains **FAIL / INCOMPLETE**. The corrected linear subcase passes, but the angular response is below its measurable gate. Moving-timeout, source-switch, moving e-stop, moving SIGTERM and physical serial unplug/reconnect were not executed after that failure. Per the ordered gate rule, T036 and every D2-D4 physical motion task remain blocked. No D1 PASS is claimed.

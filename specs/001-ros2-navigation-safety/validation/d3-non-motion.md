# D3 Navigation Non-motion Validation

**Status**: PASS — T051 completed on 2026-07-13
**Target**: runtime-configured vehicle endpoint
**Release**: `20260713T112841Z`
**Safety scope**: Nav2/AMCL startup and read-only interface checks using a provisional stationary map; no navigation goal, patrol, return-home, simulated low battery or non-zero velocity command

## Preconditions and bounded input

The final campus map does not exist, so this startup check used only the non-motion provisional map. One initial-pose message at `(0, 0, 0)` was supplied so AMCL could establish `map→odom`; an initial pose is not a motion request. `patrol_route.yaml` remained `configured: false` with null coordinates.

## Runtime result

| Check | Observed | Required | Result |
|---|---:|---:|---:|
| Safety/source/alarm | `READY` / `NONE` / no alarm event | healthy / idle | PASS |
| `/cmd_vel` | 160 samples at 19.968 Hz; 0 non-zero | sole arbiter, all zero | PASS |
| `/scan` | 65 samples at 8.112 Hz; `laser_link` | ≥5 Hz / correct frame | PASS |
| `/odom` | 241 samples at 30.077 Hz | ≥20 Hz | PASS |
| `/map` | transient-local map received once; 206×94 at 0.05 m | map server visible | PASS |
| Localization/navigation nodes | AMCL, map server, planner, controller, BT navigator, recoveries and patrol manager present | required nodes | PASS |
| Mapping exclusion | no Cartographer node | Cartographer absent | PASS |
| TF ownership | AMCL supplies `map→odom`; EKF supplies `odom→base_footprint` | unique role owners | PASS |
| Speed routing | controller/recoveries publish `/cmd_vel_nav`; `/cmd_vel` publisher is only `cmd_vel_arbiter` | required remap/boundary | PASS |
| NavigateToPose | Foxy send/get-result/cancel services visible; one server (`bt_navigator`) | action available | PASS |
| Patrol safety | status is `IDLE`, `route_configured=false` | inert route | PASS |

The installed `verify_navigation.sh` read-only check also passed action-client/server, remap, topic-owner and TF gates. No goal was sent, and the final launch log had no fatal marker. Raw collector record `20260713T113209Z-d3` is local-only and ignored.

## Conclusion

T051: **PASS**. This is configuration/startup evidence only. T052 and all navigation/patrol performance criteria remain **PENDING** until D2 has a final accepted map and the user explicitly approves physical motion.

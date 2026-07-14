# D1 Safe-base Non-motion Validation

**Status**: PASS — T034 completed on 2026-07-13
**Target**: runtime-configured vehicle endpoint
**Release**: `20260713T112841Z`
**Launch limits**: `max_linear=0.05 m/s`, `max_angular=0.20 rad/s`
**Motion commands sent**: none; no manual publisher, Nav2 goal, patrol or return request was used

## Runtime result

A bounded read-only collector subscribed for 8.005 seconds after final safe-base startup. The launch set `ROS_LOCALHOST_ONLY=1` and the installed Fast DDS profile; the probe joined that same container-local DDS graph.

| Check | Observed | Gate | Result |
|---|---:|---:|---:|
| `/scan` | 63 samples, 7.871 Hz | ≥5 Hz | PASS |
| `/odom` | 179 samples, 22.362 Hz | ≥20 Hz | PASS |
| `/cmd_vel` | 161 samples, 20.114 Hz | all zero | PASS (0 non-zero) |
| Scan frame | `laser_link` | `laser_link` | PASS |
| Odom frames | `odom` → `base_footprint` | required chain | PASS |
| Chassis heartbeat | `True`, about 10 Hz | connected/fresh | PASS |
| Active source | `NONE` | no source | PASS |
| Safety state | `READY` | healthy | PASS |

Publisher ownership was unique: `/cmd_vel=cmd_vel_arbiter`, `/scan=sllidar_node`, `/odom=ekf_filter_node`. TF contained `odom→base_footprint→base_link→laser_link`; no `map→odom` transform existed in base mode. `/tf_static` was owned by `robot_state_publisher`; dynamic `/tf` owners matched robot state, IMU filter and EKF roles.

## Runtime corrections discovered

- Fast DDS participant discovery was incomplete over host-network/Wi-Fi and after participant churn. The installed UDPv4 profile is restricted to `127.0.0.1` and increases `maxInitialPeersRange` from 4 to 64; a full collector remained complete after 11 short-lived probe participants while preserving external rosbridge WebSocket access.
- Target `robot_localization 3.1.2` suppresses duplicate measurement timestamps. Reducing its prediction threshold to 0.02 seconds restored the configured 30 Hz `/odom` output between 10 Hz raw samples.
- Adding a zero-valued JointState position array removed repeated robot-state-publisher warnings.

The final launch log contained no process error or traceback. Raw collector record `20260713T113739Z-d1` is stored under ignored `artifacts/navigation/raw/`; its metadata records `readOnly=true`, `motionCommandsSent=false` and `credentialsIncluded=false`.

## Conclusion

T034: **PASS**. T035 remains **PENDING USER APPROVAL**; therefore the overall D1 gate is not yet PASS.

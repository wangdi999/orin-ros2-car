# Local Implementation Status

**Recorded**: 2026-07-13
**Overall status**: SOFTWARE AND NON-MOTION IMPLEMENTATION VERIFIED; D1 MOTION GATE FAILED AND IS BLOCKED

## Implemented and verified

- `car_interfaces/Alarm` and legacy `/alarm_events` compatibility.
- Hardened X3 driver limits, finite-value rejection, 300 ms watchdog, graceful zero, serial reconnect and `/chassis/connected` heartbeat.
- Raw X3 odometry integration with first-frame/invalid-`dt` handling, lateral velocity and nonzero covariance.
- EKF ownership of `/odom` and `odom -> base_footprint`.
- Sole `/cmd_vel` arbiter with manual/navigation inputs, zero-before-switch, stale-heartbeat fail-closed behavior and persistent patrol-cancel retry.
- Safety state, explicit reset gates, topic/mode ownership checks, TF checks, simulated low-battery return and real-low-battery opt-in protection.
- Cartographer mapping, atomic map-release save helper, AMCL/Nav2 Foxy configuration, patrol/return-home state machine and inert route template.
- Console manual topic migration, estop/reset Trigger handling, patrol services, typed alarm handling, safety/source/patrol status and managed launch profiles.
- Staged deployment and read-only evidence scripts without embedded credentials.
- Connection/development documentation for endpoint `192.168.160.196`, runtime modes and motion approval.
- Local regression: 46 console + 7 driver + 63 navigation tests, all passed; console production build passed.
- Target Foxy build/test: release `20260713T112841Z`, 80 tests with 0 errors/failures/skips.
- Vehicle safe-base: scan 7.871 Hz, odom 22.362 Hz, sole final velocity publisher and zero output.
- Vehicle mapping profile: Cartographer present, AMCL absent, map topic present and one `map→odom` role owner.
- Vehicle navigation profile: AMCL/Nav2 present, Cartographer absent, Nav2 output remapped upstream of the sole arbiter; no goal sent.
- Zero-only and process-fault probes: timeout/e-stop/reset plus lidar, EKF and driver termination remained zero and entered matching safety states.

## Physical gate status

- After a car reboot and strengthened feedback preflight, the bounded `0.05 m/s` linear retest passed: 0.018308 m fused displacement and 0.020 s explicit stop latency.
- The next `0.20 rad/s` angular pulse remained bounded and ended at zero, but raw yaw reached only 0.016592 rad and fused yaw 0.003557 rad, below the 0.02 rad gate. T035 remains failed/incomplete.
- Moving timeout, source-switch, e-stop, SIGTERM and physical serial unplug/reconnect cases were not executed after the angular failure.
- The non-motion provisional map is not an accepted `campus_map`; no measured route or five-landmark map-quality evidence exists.
- `patrol_route.yaml` remains `configured: false` with null coordinates.
- No Nav2 goal, patrol, return-home or simulated-low-battery return has run.
- No D1-D4 day gate is marked PASS, and no final physical acceptance is claimed.

## Resume boundary

The next ordered task remains T035. Before retrying the angular subcase, record whether the operator observed physical rotation, retain the `0.20 rad/s` ceiling, use a justified longer bounded pulse rather than lowering the evidence threshold, and send zero afterward.

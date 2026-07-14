# Requirements Traceability

**Reviewed**: 2026-07-13
**Coverage result**: 32/32 functional requirements have implementation tasks and an explicit evidence destination
**Status legend**: `VERIFIED-SOFTWARE` is backed by automated local/Foxy tests; `VERIFIED-NON-MOTION` additionally has vehicle runtime evidence; `PARTIAL` has verified components but still needs final map or motion evidence; `PENDING-MAP`/`PENDING-MOTION` has not met its acceptance condition.

| Requirement | Primary implementation/evidence | Status |
|---|---|---|
| FR-001 | D1-D4 profile chain, tasks and final-acceptance table | PARTIAL — software/non-motion complete; ordered physical gates open |
| FR-002 | Hardened `icar_bringup`/`icar_base_node`, Foxy build and live chassis heartbeat | VERIFIED-NON-MOTION |
| FR-003 | Independent manual/nav topics, owner checks and sole live `/cmd_vel` arbiter | VERIFIED-NON-MOTION |
| FR-004 | Priority/fail-closed policy tests plus live source/safety outputs | VERIFIED-NON-MOTION |
| FR-005 | Zero-before-switch and persistent cancel/inhibit tests | VERIFIED-SOFTWARE — takeover motion pending |
| FR-006 | Driver finite-value, hard-limit and watchdog tests; zero-only timeout probe | VERIFIED-SOFTWARE — moving response pending |
| FR-007 | Shutdown-zero/reconnect code and 10 Hz live heartbeat; driver SIGTERM fault probe | PARTIAL — physical serial unplug/reconnect pending |
| FR-008 | Odometry gtests and live EKF `/odom` at 22.362–30.077 Hz | VERIFIED-NON-MOTION |
| FR-009 | Live `/scan` at 7.871–8.125 Hz with `laser_link` | VERIFIED-NON-MOTION |
| FR-010 | Live TF/topic owners in base, mapping and navigation; EKF/lidar fault probes | VERIFIED-NON-MOTION |
| FR-011 | Live EKF `/odom`/dynamic TF and robot-state fixed-TF ownership | VERIFIED-NON-MOTION |
| FR-012 | Mutually exclusive launch/config tests; separate live mapping and localization owners | VERIFIED-NON-MOTION |
| FR-013 | Cartographer external odom plus transactional Foxy save of provisional sibling artifacts | PARTIAL — final `campus_map` pending |
| FR-014 | Map-artifact tests and D2 quality procedure | PENDING-MAP — reload/landmark/corridor/wall evidence absent |
| FR-015 | Foxy Nav2 config, live AMCL/Nav2 and `/cmd_vel_nav` remap | PARTIAL — accepted map and motion pending |
| FR-016 | Foxy action contract and success/failure/timeout/cancel policy tests; action server visible | VERIFIED-SOFTWARE — goal execution pending |
| FR-017 | 0.15/0.15 configuration tests and T052 measurement destination | PENDING-MOTION |
| FR-018 | Strict route/schema tests and inert null-coordinate template | PARTIAL — final-map coordinates pending |
| FR-019 | Patrol state/mode/freshness tests and live `IDLE`, `route_configured=false` heartbeat/services | VERIFIED-NON-MOTION |
| FR-020 | Three-second dwell, one-retry, skip and non-loop policy tests | VERIFIED-SOFTWARE |
| FR-021 | Fault/manual/cancel termination and no-auto-resume tests | VERIFIED-SOFTWARE — physical behavior pending |
| FR-022 | Live e-stop latch/reset plus visible safety/patrol Trigger services | PARTIAL — simulated-low-battery return intentionally not invoked |
| FR-023 | Generated `Alarm.msg`, compatibility stream tests and matching process-fault states/alarms | PARTIAL — serial/navigation/return physical cases pending |
| FR-024 | Console typed/legacy alarm handling within 46/46 Node tests | VERIFIED-SOFTWARE |
| FR-025 | Simulated service/real-disabled configuration and policy tests | VERIFIED-SOFTWARE — return movement pending |
| FR-026 | Ten-sample/10.8 V/5 s/11.1 V policy tests | VERIFIED-SOFTWARE |
| FR-027 | Return-failure lock/zero/critical-alarm tests | VERIFIED-SOFTWARE — unreachable-Home movement pending |
| FR-028 | Localized console changes, 46/46 tests and production build | VERIFIED-SOFTWARE |
| FR-029 | Read-only collector plus D1/D2/D3 and D4 partial summaries | PARTIAL — motion timing/map/demo evidence pending |
| FR-030 | Preserved dirty tree, ignored raw artifacts, redacted deployment/collector dry-runs | VERIFIED-SOFTWARE |
| FR-031 | Parameterized runtime endpoint checks and enforced motion-gate boundary | VERIFIED-NON-MOTION |
| FR-032 | Hard/soft limit tests and documented zero-after-test procedure | PARTIAL — first physical pulse not run |

T078 is complete because every FR has a buildable implementation task, a current evidence status and a named remaining gate where applicable: **32/32 (100%) task/evidence coverage**. Coverage is not acceptance; T035/T043-T045/T052/T059-T061/T070-T073 remain open and no D1-D4 physical gate is claimed PASS.

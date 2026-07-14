# Final Acceptance

**Status**: FAIL-D1-MOTION / PENDING-RETEST
**Current release**: `20260713T112841Z`
**Current vehicle state**: post-failure preflight `20260713T124259Z-d1-motion`; safe-base `READY`, active source `NONE`, chassis connected, five managed publishers unique, 59/59 observed outputs zero, no observed alarm

| Gate | Status | Blocking evidence |
|---|---|---|
| D1 safe base | FAIL / BLOCKED | corrected `0.05 m/s` linear pulse PASS with 0.020 s stop latency; `0.20 rad/s` angular pulse produced only 0.016592 rad raw yaw, below the 0.02 rad response gate; remaining T035 cases stopped |
| D2 mapping | PENDING-MOTION | T042 mapping startup/ownership/map topic PASS; final `campus_map`, measured route and T044 quality/reload evidence absent |
| D3 navigation/patrol | PENDING-MOTION | T051 AMCL/Nav2/action/remap startup PASS with a provisional map and no goal; single-goal, route and patrol evidence absent |
| D4 faults/return/demo | PENDING-MOTION | zero-only e-stop/timeout plus lidar, EKF and driver process faults PASS; physical serial, simulated return-home and two full demos absent |

Software, Foxy compatibility and all non-motion paths remain verified. This document intentionally does not claim a D1-D4 gate PASS. The next executable task is a justified T035 angular retest at the same speed ceiling; no later physical task may start until it passes.

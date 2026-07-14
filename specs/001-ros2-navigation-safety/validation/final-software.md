# Final Software and Non-motion Validation

**Status**: PASS — T077 completed on 2026-07-13
**Target release**: `20260713T112841Z` on ROS 2 Foxy
**Motion commands sent**: none

## Tool versions

- Local: Python 3.13.5, Node.js 22.19.0, npm 10.9.3, Windows PowerShell 5.1.
- Console build: Vite 6.4.3.
- Vehicle: ROS 2 Foxy in `icar/ros-foxy:1.0.2`.

## Automated results

| Layer | Command/scope | Result |
|---|---|---:|
| Console | `npm test` | 46/46 passed |
| Console production | `npm run build` | PASS; 35 modules transformed; size warning only |
| Driver pure logic | `python .../test_driver_safety.py` | 7/7 passed |
| Navigation pure/config | `python -m unittest discover ...` | 63/63 passed |
| Local syntax | `python -m compileall -q ...` | PASS |
| PowerShell syntax | AST parse of deploy, collector and fault scripts | 3/3 passed |
| Foxy packages | `colcon build/test` for four scoped packages | 80 tests; 0 errors/failures/skipped |

Local automated total is **116** assertions/tests (46 + 7 + 63). Foxy reports **80** package tests (6 base-node gtests + 10 bringup + 63 navigation, plus interface/package checks represented by colcon's aggregate).

## Quickstart non-motion execution

- Immutable staged deployment and promotion passed; host/container `.ready` markers identify release `20260713T112841Z`.
- Deployment dry-run with `-UseConsoleConfig` showed only redacted credentials and explicitly performed no copy or remote command.
- Evidence-collector dry-run with `-UseConsoleConfig` performed no network connection or evidence write.
- Static source audit found no publisher, service client or action client in the read-only ROS probe; matching strings in the wrapper are guard expressions that reject mutating commands/APIs.
- Safe-base, mapping and navigation profiles passed the bounded read-only checks in `d1-non-motion.md`, `d2-non-motion.md` and `d3-non-motion.md`.
- Zero-only emergency/timeout and process-fault checks retained zero final output; physical serial unplug and all motion-dependent checks remain open.

## Safety conclusion

T077 is complete for software and non-motion scope. This result does not pass D1-D4 physical gates and does not authorize a non-zero command, goal, patrol, return-home request or mapping teleoperation.

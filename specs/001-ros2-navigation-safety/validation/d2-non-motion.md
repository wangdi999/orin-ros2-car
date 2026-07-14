# D2 Mapping Non-motion Validation

**Status**: PASS — T042 completed on 2026-07-13
**Target**: `192.168.160.196`
**Release**: `20260713T112841Z`
**Safety scope**: mapping startup and read-only graph/topic/TF inspection only; no teleoperation or non-zero velocity command

## Runtime result

The final mapping profile ran Cartographer with external odometry and the Foxy target executable `occupancy_grid_node`. A bounded 8.000-second collector observed:

| Check | Observed | Required | Result |
|---|---:|---:|---:|
| Safety/source | `READY` / `NONE` | healthy / no source | PASS |
| `/cmd_vel` | 160 samples at 20.000 Hz; 0 non-zero | all zero | PASS |
| `/scan` | 65 samples at 8.125 Hz; `laser_link` | ≥5 Hz / correct frame | PASS |
| `/odom` | 240 samples at 29.999 Hz; `odom→base_footprint` | ≥20 Hz / correct frames | PASS |
| `/map` | 8 samples at 1.000 Hz; 208×101 at 0.05 m | visible OccupancyGrid | PASS |
| Mapping owner | `cartographer_node` present; `cartographer_occupancy_grid` publishes `/map` | Cartographer present | PASS |
| Localization exclusion | no `amcl` node | AMCL absent | PASS |
| `map→odom` | present, dynamic TF includes Cartographer | exactly mapping owner | PASS |

The final mapping launch log contained no `ERROR`, `FATAL` or traceback marker. Raw collector record `20260713T113546Z-d2` is local-only and ignored.

## Save-path compatibility check

Without moving the car, the Foxy `WriteState` request and transactional save helper produced a provisional validation set on the vehicle:

- `/root/maps/non_motion_validation/provisional_map.pbstream` (253746 bytes)
- `/root/maps/non_motion_validation/provisional_map.pgm` (19378 bytes)
- `/root/maps/non_motion_validation/provisional_map.yaml` (132 bytes)

The YAML refers to sibling `provisional_map.pgm`, and that resolved file exists. These temporary stationary artifacts validate the Foxy save contract and atomic sibling naming only. They are not `campus_map`, are not committed, and do not satisfy T043/T044 map-route or map-quality acceptance.

## Conclusion

T042: **PASS**. D2 remains **PENDING MOTION APPROVAL AND D1 GATE** because final mapping and measured map-quality tasks T043-T045 have not run.

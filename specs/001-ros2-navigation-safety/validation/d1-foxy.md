# D1 Foxy Build and Interface Validation

**Status**: PASS — T033 completed on 2026-07-13
**Target**: `jetson@192.168.160.196`, Docker image `icar/ros-foxy:1.0.2`, ROS 2 Foxy
**Promoted release**: `20260713T112841Z`
**Motion commands sent**: none

## Build and test result

The four scoped packages were copied to an immutable staging workspace, built with `--merge-install`, tested, and promoted only after a zero-failure result:

| Package/scope | Result |
|---|---:|
| `car_interfaces` generated interface | PASS |
| `icar_base_node` C++ gtest | 6/6 passed |
| `icar_bringup` safety, scoped lint and license checks | 10/10 passed |
| `icar_navigation` policies/contracts/artifacts | 63/63 passed |
| `colcon test-result --verbose` | 80 tests, 0 errors, 0 failures, 0 skipped |

The promoted host and container `.ready` marker resolve to the same release. The deployment stage itself did not start runtime nodes; runtime profile validation was performed separately after promotion.

## Foxy interface evidence

- `car_interfaces/msg/Alarm` generated with INFO/WARNING/ERROR/CRITICAL constants and all required fields.
- `nav2_msgs/action/NavigateToPose.Result` is exactly `std_msgs/Empty result`; success/failure must use action terminal status.
- `action_msgs/srv/CancelGoal.Request` contains `goal_info`; the cancel-all request used by the arbiter is Foxy-compatible.
- Imports of `cmd_vel_arbiter`, `safety_manager` and `patrol_manager` succeeded under Python 3.8/Foxy.
- `safe_base`, `mapping`, `navigation` and `demo` all passed `ros2 launch ... --show-args` without starting nodes.
- The installed Fast DDS loopback profile parses under the target Fast DDS 2.1.2 runtime and is included in the merged package share.

## Fail-safe deployment audit

Three pre-promotion failures were retained as immutable failed releases and never became active: Foxy setup under `set -u`, a missing `--merge-install` on `colcon test`, and repository-wide vendor lint debt. The script was corrected, lint was scoped to the maintained X3 safety surface, and the final default test run passed without exclusions.

## Conclusion

T033: **PASS**. The current promoted overlay is build- and interface-compatible with the inspected Foxy runtime.

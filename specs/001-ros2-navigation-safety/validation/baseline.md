# Baseline: ROS2 Navigation Safety

**Recorded**: 2026-07-12
**Current vehicle endpoint**: supplied at runtime from ignored local configuration
**Safety boundary**: no non-zero command or navigation goal was sent while recording this baseline.

## Repository state before Spec Kit initialization

The repository already contained user changes. They are preserved and must not be reset, checked out, staged, reformatted, or overwritten as unrelated work.

```text
 M docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md
 M smart-car-console/.gitignore
 M smart-car-console/local-config.example.json
 M smart-car-console/package-lock.json
 M smart-car-console/package.json
 M smart-car-console/server/config.mjs
 M smart-car-console/server/control.mjs
 M smart-car-console/server/control.test.mjs
 M smart-car-console/server/index.mjs
 M smart-car-console/server/keyboardDrive.test.mjs
 M smart-car-console/server/rosbridge.mjs
 M smart-car-console/server/serviceManager.mjs
 M smart-car-console/server/state.mjs
 M smart-car-console/src/App.jsx
 M smart-car-console/src/styles.css
 ?? additional user-owned console modules/tests, tmp/, and 需求分析报告.md
```

Spec Kit subsequently added only `.specify/`, `.agents/`, `specs/`, and the managed block in `AGENTS.md`; ROS navigation implementation files are scoped under `ros2_car_remote_ws/src/` and `scripts/`.

## Console test baseline

Command executed before navigation changes:

```powershell
Set-Location smart-car-console
npm test
```

Result: **36/36 tests passed**. The initial sandbox run was blocked by Windows process spawning; the identical command succeeded in the normal workspace runtime. This is the regression floor for later console changes.

## Read-only vehicle baseline

Observed on an earlier runtime endpoint; all facts must be rechecked at the current configured endpoint before deployment:

- ROS distribution: Foxy.
- Running functional nodes: chassis driver, SLLIDAR and rosbridge; no odometry, map or TF owner.
- `/scan`: about 7.7 Hz, but `header.frame_id=laser` while the installed URDF uses `laser_link`.
- `/vel_raw`, `/voltage`, `/imu/data_raw`: about 10 Hz; voltage was about 11.3 V.
- `/odom`, `/map`, `/tf`, `/tf_static`: no active publisher at that baseline.
- Installed target packages include Cartographer ROS, Nav2 bringup/AMCL/Map Server/NavFn/DWB/BT/Waypoint, robot_localization, tf2_ros, `icar_base_node`, `icar_bringup` and SLLIDAR.
- Target Foxy `nav2_msgs/action/NavigateToPose` result contains `std_msgs/Empty result`; action status is required for success/failure.

## Secret and artifact protection

- `smart-car-console/local-config.json` is ignored by both root and console ignore rules and was not read into this document or modified.
- Passwords, SSH host keys, device credentials and raw runtime logs are excluded.
- Raw rosbag and unredacted evidence belongs under ignored `artifacts/navigation/raw/`.

## Baseline gate

- Existing user changes preserved: **PASS**
- Console 36/36 baseline: **PASS**
- Physical movement during baseline: **NONE**
- Updated runtime endpoint SSH/runtime recheck: **PASS** (T033/T034; no non-zero command sent)

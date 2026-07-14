# Quickstart: ROS2 核心与导航四天闭环

本指南把验证分为三类：本地无硬件、车端非运动/零速度、经用户批准后的实车运动。车端地址从本地配置读取；不要把密码、host key 或 `local-config.json` 写入命令记录。

> **测试已恢复（2026-07-13）**：用户已授权本地测试以及车端构建、只读、非运动和显式零速度检查。任何非零 Twist、Nav2 goal、巡航、返航、模拟低电返航或建图遥控仍须另行汇报，并等待用户明确确认轮子架空或场地已清空。

## 0. Safety boundary

- 本地测试、编译、网络/端口检查、只读 topic/TF/参数检查和显式零速度检查可直接执行。
- 启动导航组件但不发送 goal 属于非运动检查；必须先确认最终 `/cmd_vel` 为零且只有仲裁器一个常规发布者。
- 任何非零 Twist、Nav2 goal、巡航、返航或建图遥控都属于物理运动测试。
- 在第一次物理运动前停止执行并请用户确认“轮子架空”或“场地已清空”。第一轮不超过 `0.05 m/s`、`0.20 rad/s`，通过后不超过 `0.10 m/s`、`0.40 rad/s`；每项结束必须发零。

## 1. Local, no-hardware validation

记录并保护当前工作树：

```powershell
git status --short
git diff -- smart-car-console ros2_car_remote_ws
```

运行控制台测试和构建：

```powershell
Set-Location D:\code\project\smart-car-remote-control-20260707\smart-car-console
npm test
npm run build
```

运行不依赖 ROS 导入的策略测试：

```powershell
Set-Location D:\code\project\smart-car-remote-control-20260707
python -m pytest ros2_car_remote_ws\src\icar_bringup\test\test_driver_safety.py ros2_car_remote_ws\src\icar_navigation\test -q
```

## 2. Connectivity and target runtime checks (non-motion)

```powershell
$CarIp = (Get-Content .\smart-car-console\local-config.json -Raw | ConvertFrom-Json).car.host
Test-NetConnection $CarIp -Port 22
Test-NetConnection $CarIp -Port 9090
Test-NetConnection $CarIp -Port 5900
```

Read-only target checks:

```powershell
ssh "jetson@$CarIp" "docker ps --format '{{.Names}} {{.Status}}'"
ssh "jetson@$CarIp" "docker exec smartcar_icar_console bash -lc 'source /opt/ros/foxy/setup.bash && printenv ROS_DISTRO && ros2 pkg list | grep -E \"^(cartographer_ros|nav2_bringup|nav2_amcl|robot_localization)$\"'"
```

车端 ROS 节点统一运行在容器 loopback DDS 图谱中；在容器里手工执行 `ros2` 检查前先设置 `ROS_LOCALHOST_ONLY=1`，并将 `FASTRTPS_DEFAULT_PROFILES_FILE` 指向已安装的 `config/fastdds_localhost.xml`。该 profile 把 UDPv4 限定到 `127.0.0.1` 并把 initial-peer range 扩为 64。Windows 控制台仍通过外部 `ws://<car-ip>:9090` 连接 rosbridge，不直接加入 DDS。

## 3. Deploy to a staging overlay (non-motion)

The deployment script copies only the four scoped ROS packages into an immutable release under `/home/jetson/ros2_navigation_overlay`. It promotes the managed overlay only after a successful build and default test run, never replaces the base image workspace, and never starts runtime nodes:

```powershell
Set-Location D:\code\project\smart-car-remote-control-20260707
.\scripts\deploy_ros2_navigation.ps1 -CarIp $CarIp -DryRun
.\scripts\deploy_ros2_navigation.ps1 -CarIp $CarIp -UseConsoleConfig
```

`-UseConsoleConfig` reads the ignored `smart-car-console/local-config.json` only at runtime and redacts both password and host key from command display. Omit it when OpenSSH key authentication is configured.

Equivalent container build check:

```bash
source /opt/ros/foxy/setup.bash
cd /root/ros2_navigation_overlay
colcon build --merge-install --packages-select car_interfaces icar_base_node icar_bringup icar_navigation
source install/setup.bash
colcon test --packages-select car_interfaces icar_base_node icar_bringup icar_navigation
colcon test-result --verbose
ros2 interface show car_interfaces/msg/Alarm
ros2 interface show nav2_msgs/action/NavigateToPose
```

Expected Foxy `NavigateToPose` result contains `std_msgs/Empty result`; any design expecting a result error code fails this gate.

## 4. Safe-base startup and zero-only verification (non-motion)

Before starting, inspect existing owners and stop any legacy direct teleop that publishes `/cmd_vel`:

```bash
ros2 topic info /cmd_vel --verbose
ros2 node list
```

Launch the staged safe base with motion soft-limited to the first-test values. Do not send a non-zero command:

```bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
ros2 launch icar_navigation safe_base.launch.py \
  max_linear:=0.05 max_angular:=0.20 lidar_frame:=laser_link
```

In another shell, verify ownership, rate, frames, state and an explicit zero request:

```bash
ros2 topic info /cmd_vel --verbose
ros2 topic hz /scan
ros2 topic hz /odom
ros2 topic echo --once /scan
ros2 topic echo --once /chassis/connected
ros2 topic echo --once /control/active_source
ros2 topic echo --once /safety/state
ros2 topic pub --once /cmd_vel_manual geometry_msgs/msg/Twist \
  "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

Expected:

- exactly one normal `/cmd_vel` publisher, `cmd_vel_arbiter`;
- `/scan` frame is `laser_link` and rate is at least 5 Hz;
- `/odom` rate is at least 20 Hz;
- TF contains one `odom → base_footprint` and no `map → odom` in base-only mode;
- final Twist remains zero.

Zero-only emergency and reset check:

```bash
ros2 topic pub --once /safety/estop std_msgs/msg/Bool "{data: true}"
ros2 topic echo --once /safety/state
ros2 topic echo --once /alarm
ros2 topic pub --once /safety/estop std_msgs/msg/Bool "{data: false}"
ros2 service call /safety/reset std_srvs/srv/Trigger "{}"
```

## 5. Mapping configuration check (non-motion)

Stop base-only launch and start mapping without sending teleop commands:

```bash
ros2 launch icar_navigation mapping.launch.py \
  max_linear:=0.05 max_angular:=0.20 lidar_frame:=laser_link
```

Verify:

```bash
ros2 node list | grep -E "cartographer|amcl"
ros2 run tf2_ros tf2_echo map odom
ros2 topic info /map --verbose
```

Expected: Cartographer is present, AMCL is absent, and there is one `map → odom` owner.

## 6. Navigation configuration check (non-motion)

Stop mapping before launching navigation:

```bash
ros2 launch icar_navigation navigation.launch.py \
  map:=/root/ros2_navigation_overlay/install/share/icar_navigation/maps/campus_map.yaml \
  max_linear:=0.05 max_angular:=0.20
```

Without setting an initial pose or goal, verify:

```bash
ros2 node list | grep -E "amcl|planner_server|controller_server|bt_navigator|cartographer"
ros2 topic info /cmd_vel_nav --verbose
ros2 topic info /cmd_vel --verbose
ros2 action info /navigate_to_pose
```

Expected: AMCL/Nav2 are present, Cartographer is absent, Nav2 owns `/cmd_vel_nav`, and the arbiter remains the sole normal `/cmd_vel` publisher.

## 7. Mandatory pause before physical movement

**STOP HERE.** Report the completed automated/non-motion results and wait for explicit user approval that either:

1. the wheels are lifted and free to rotate, or
2. the indoor route is cleared with an operator ready at emergency stop.

No command below this point may be executed before that approval.

## 8. D1 first motion and fault tests (approval required)

Start with `max_linear=0.05`, `max_angular=0.20`. Use short pulses through `/cmd_vel_manual`, never direct non-zero `/cmd_vel`, and immediately send zero after each pulse. Measure arbiter output and wheel response. Then test command timeout, source switch, estop and controlled serial unplug/replug. Every case ends in zero and an evidence record.

Only after D1 passes may mapping begin.

## 9. D2 mapping (approval required)

Teleoperate the cleared route at approved limits, close loops slowly, then save the same session:

```bash
ros2 run icar_navigation save_map.sh campus_map
```

Record two map-server reloads and five landmark comparisons. Do not proceed if the map has a broken corridor, landmark error above 0.20 m, or duplicate-wall separation above 0.15 m.

## 10. D3 navigation and patrol (approval required)

Enter measured Home and three waypoint coordinates in `config/patrol_route.yaml`, set `configured: true`, review the diff, then launch navigation at approved limits. Validate one goal first, then two complete three-point patrol rounds, then a deliberately unreachable point with exactly one retry and a skip alarm.

## 11. D4 simulated low battery and demo (approval required where movement occurs)

With localization healthy and Home reviewed:

```bash
ros2 service call /safety/simulate_low_battery std_srvs/srv/Trigger "{}"
```

Verify cancellation, Home return and stop. Separately test an unreachable Home and confirm zero-speed latch with `RETURN_HOME_FAILED`. Keep `enable_real_low_battery=false`.

## 12. Evidence collection

```powershell
Set-Location D:\code\project\smart-car-remote-control-20260707
.\scripts\collect_navigation_evidence.ps1 -CarIp $CarIp -Gate d1 -UseConsoleConfig
```

Store raw output under `artifacts/navigation/raw/` (ignored). Commit only concise, scrubbed acceptance summaries and generated map artifacts approved for version control. The collector is read-only and never marks a gate PASS by itself.

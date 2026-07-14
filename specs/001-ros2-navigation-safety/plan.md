# Implementation Plan: ROS2 核心与导航四天闭环

**Branch**: `001-ros2-navigation-safety` | **Date**: 2026-07-12 | **Spec**: [spec.md](./spec.md)

**Input**: [功能规格](./spec.md) 与目标小车 ROS 2 Foxy 运行时的只读接口核验结果。

## Summary

在现有 X3 底盘、控制台和 Foxy 软件栈上增量建立三层闭环：底层驱动独立执行有限值校验、硬限幅、300 ms watchdog、终止归零和串口恢复；中层由速度仲裁与安全状态机独占最终 `/cmd_vel`、监控底盘/激光/里程计/TF 并锁存故障；上层提供互斥的 Cartographer 建图与 AMCL/Nav2 导航模式，以及基于 Foxy `NavigateToPose` 动作终态的三点巡航和低电返航。代码先通过纯逻辑、静态和 Foxy 构建验证，再在用户批准后按 `0.05/0.20 → 0.10/0.40` 分级完成实车运动验收。

## Technical Context

**Language/Version**: Python 3.8（ROS 2 Foxy 节点和 launch）、C++14（`icar_base_node`）、JavaScript ES modules（现有控制台）

**Primary Dependencies**: ROS 2 Foxy `rclpy`/`rclcpp`、`geometry_msgs`、`nav_msgs`、`sensor_msgs`、`std_msgs`、`std_srvs`、`tf2_ros`、`robot_localization`、Cartographer ROS、Nav2 AMCL/Map Server/NavFn/DWB/BT Navigator、PyYAML、现有 `Rosmaster_Lib`、现有 Node.js 控制台

**Storage**: 版本化 YAML/Lua/URDF/launch 配置；`campus_map.pgm/.yaml/.pbstream` 地图产物；忽略目录中的 JSON/文本验收证据和 rosbag

**Testing**: `pytest`/`ament_pytest`（纯逻辑与 Python ROS 包）、`ament_cmake_gtest`（里程计积分逻辑）、launch/XML/YAML 静态检查、`npm test` 与 `npm run build`、目标车 Foxy `colcon build/test`、分级实车验收

**Target Platform**: Jetson Orin Nano，Ubuntu 20.04，Docker 镜像 `icar/ros-foxy:1.0.2`；Windows 控制台为开发和操作端

**Project Type**: 多 ROS 包机器人系统 + 现有本地 Web 控制台

**Performance Goals**: `/scan ≥ 5 Hz`，`/odom ≥ 20 Hz`；命令失联 0.40 秒内归零；其他运动相关故障 0.50 秒内归零并告警；串口每 5 秒重连；导航初始上限 0.10 m/s、0.40 rad/s

**Constraints**: Foxy 已 EOL，只能使用目标车已安装接口；`/cmd_vel` 单一常规写入者；mapping/localization 模式互斥；无非零实车命令直至用户确认；不得覆盖现有脏工作树或泄露本地凭据

**Scale/Scope**: 1 台 X3 小车、1 个受控室内地图、1 个 Home + 3 个航点、4 个 ROS 包、约 10 个公共 topic、5 个服务、5 类用户故事、4 个日门禁

## Constitution Check

*GATE: Phase 0 前和 Phase 1 设计后均已复核。任何一项失效都阻止下一日门禁。*

- [x] 物理运动与代码、构建、网络、只读 topic/TF 和零速度验证明确分离；quickstart 在首个非零命令前设置人工批准停止点。
- [x] `cmd_vel_arbiter` 是唯一常规 `/cmd_vel` 发布者；仅保留 SSH 直接发零的灾难恢复通道。
- [x] topic/TF 所有者写入 contracts；Cartographer 和 AMCL 通过互斥 launch 模式隔离。
- [x] 驱动硬限幅、300 ms watchdog、终止归零、串口重连、故障锁存和显式复位均进入设计与测试。
- [x] 设计只使用已在目标 Foxy 环境核验的消息、动作和插件；`NavigateToPose.Result` 按 `std_msgs/Empty` 处理。
- [x] 每个运动与故障需求均对应自动化测试、非运动车端检查或明确的实车证据任务。
- [x] `local-config.json`、SSH 资料、原始 rosbag 和用户已有未提交改动均在保护边界内。

### Post-design Re-check

- [x] [research.md](./research.md) 的每项关键决策均说明了 Foxy 与安全依据。
- [x] [contracts/ros-interfaces.md](./contracts/ros-interfaces.md) 没有第二个最终速度或关键 TF 所有者。
- [x] [data-model.md](./data-model.md) 的状态转换禁止故障后自动恢复运动。
- [x] [quickstart.md](./quickstart.md) 将非运动验证、零速度验证和需批准的运动验证分段。

## Project Structure

### Documentation (this feature)

```text
specs/001-ros2-navigation-safety/
|-- spec.md
|-- plan.md
|-- research.md
|-- data-model.md
|-- quickstart.md
|-- contracts/
|   |-- ros-interfaces.md
|   `-- route.schema.yaml
|-- checklists/
|   |-- requirements.md
|   `-- safety-navigation.md
`-- tasks.md
```

### Source Code (repository root)

```text
ros2_car_remote_ws/src/
|-- car_interfaces/
|   |-- msg/Alarm.msg
|   |-- CMakeLists.txt
|   `-- package.xml
|-- icar_base_node/
|   |-- include/icar_base_node/odometry_integrator.hpp
|   |-- src/base_node_X3.cpp
|   |-- src/odometry_integrator.cpp
|   |-- test/test_odometry_integrator.cpp
|   |-- CMakeLists.txt
|   `-- package.xml
|-- icar_bringup/
|   |-- icar_bringup/Mcnamu_driver_X3.py
|   |-- icar_bringup/driver_safety.py
|   |-- launch/icar_bringup_X3_launch.py
|   |-- param/imu_filter_param.yaml
|   `-- test/test_driver_safety.py
`-- icar_navigation/
    |-- icar_navigation/
    |   |-- cmd_vel_arbiter.py
    |   |-- motion_policy.py
    |   |-- safety_manager.py
    |   |-- safety_policy.py
    |   |-- patrol_manager.py
    |   |-- patrol_policy.py
    |   `-- route_loader.py
    |-- config/
    |   |-- arbiter.yaml
    |   |-- safety.yaml
    |   |-- ekf.yaml
    |   |-- cartographer_2d.lua
    |   |-- nav2_foxy.yaml
    |   `-- patrol_route.yaml
    |-- launch/
    |   |-- safe_base.launch.py
    |   |-- mapping.launch.py
    |   |-- navigation.launch.py
    |   `-- demo.launch.py
    |-- maps/.gitkeep
    |-- scripts/
    |   |-- save_map.sh
    |   `-- verify_navigation.sh
    |-- test/
    |   |-- test_motion_policy.py
    |   |-- test_safety_policy.py
    |   |-- test_route_loader.py
    |   |-- test_patrol_policy.py
    |   |-- test_map_artifacts.py
    |   |-- test_alarm_contract.py
    |   `-- test_config_contracts.py
    |-- package.xml
    |-- setup.py
    `-- setup.cfg

smart-car-console/
|-- server/rosbridge.mjs
|-- server/control.mjs
|-- server/index.mjs
|-- server/serviceManager.mjs
|-- server/*.test.mjs
`-- src/App.jsx

scripts/
|-- deploy_ros2_navigation.ps1
`-- collect_navigation_evidence.ps1

artifacts/navigation/                 # ignored local evidence and rosbag output
```

**Structure Decision**: ROS 公共消息采用独立 `car_interfaces`；从车端纳入并修复原 C++ `icar_base_node`；现有 `icar_bringup` 只承担硬件边界；所有机器人专用仲裁、安全、巡航和 SLAM/Nav2 配置集中到新的 `icar_navigation`。控制台只在现有模块上做最小 topic/service/启动编排适配。

## Design and Delivery Phases

### Phase 0 - Research and Runtime Lock

- 锁定 Foxy action/result、Nav2 插件名、Cartographer frame 语义、现有串口 API 和车端 TF/URDF 所有者。
- 记录不采用的方案及原因，避免引入 post-Foxy 参数或第二套速度边界。

### Phase 1 - Contracts and Safety Foundation (D1)

- 先实现可脱离 ROS 测试的限幅、watchdog、仲裁、锁存与里程计积分核心，再接入 ROS 节点。
- 驱动、EKF、机器人描述、激光 frame、仲裁与安全管理统一由 `safe_base.launch.py` 编排。
- D1 门禁失败时，只修复安全底座，不启动建图或导航。

### Phase 2 - Mapping (D2)

- Cartographer 使用外部 `/odom`，自身不创建 odom frame；occupancy grid 和保存脚本产生三类同名地图产物。
- `mapping.launch.py` 明确排除 AMCL；地图重载与质量测量写入验收证据。

### Phase 3 - Localization, Navigation, Patrol (D3)

- `navigation.launch.py` 加载 Map Server、AMCL、NavFn、DWB、BT Navigator，并将控制器输出重映射到 `/cmd_vel_nav`。
- 巡航用顺序 `NavigateToPose` action client 实现自定义停留、重试、跳过、人工接管取消和返航；不把 Foxy 空结果误作状态码。

### Phase 4 - Fault Closure and Demo (D4)

- 安全管理器统一形成结构化 Alarm 和控制台兼容事件；真实低电默认关闭，模拟低电走同一返航状态路径。
- 一键 Demo 只组合已通过的 launch；故障注入和综合演示均保存可复核证据。

## Daily Gates

| Gate | Required evidence | Blocks |
|---|---|---|
| D1 安全底座 | topic 频率、TF 唯一性、watchdog 延迟、串口停车/恢复、零速度终态 | D2-D4 |
| D2 建图 | 三类地图产物、两次 reload、五地标测量、墙体/走廊检查 | D3-D4 |
| D3 导航巡航 | 单点误差、两轮三点记录、不可达重试/跳过告警 | D4 |
| D4 故障闭环 | 各故障停止延迟、模拟低电返航/失败锁止、两次综合 Demo | 发布完成 |

## Deployment and Rollback

- 部署脚本只复制本功能的 ROS 包与配置到车端 staging 目录，再由容器内 overlay 构建；不覆盖底层镜像工作区的未备份源码。
- 每次部署前记录目标包来源、现有节点和 topic 所有者；构建失败不切换运行 overlay。
- 启动时先只运行安全底座并验证零速度，再选择 mapping 或 navigation；停止时先取消自主 action、发布零、关闭上层、最后关闭驱动。
- 回退通过切换回部署前 overlay/启动脚本完成，禁止使用 Git reset 清除本地用户改动。

## Complexity Tracking

无宪章违例需要豁免。四个 ROS 包分别承担公共接口、里程计、硬件边界和机器人导航职责，拆分与现有 ROS 包边界一致。

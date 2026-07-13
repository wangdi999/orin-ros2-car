# ROS2 Agent Workspace

该工作空间是 LangGraph 车端编排方案的确定性 ROS2 执行层，目标环境为 Ubuntu 20.04 + ROS2 Foxy。

包含：

- `car_interfaces`：任务、告警、状态和 Service 契约。
- `car_patrol`：顺序调用 `NavigateToPose` 的 Patrol Manager。
- `car_safety`：手动/导航速度仲裁、急停、限速和 Watchdog。
- `car_bringup`：新增节点的统一 Launch。

构建：

```bash
cd ros2_agent_ws
source /opt/ros/foxy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

本仓库不包含完整 Nav2、SLAM、相机和实车依赖。只有在车端 Foxy 容器中完成 Topic、Action、TF 和设备确认后，才可进行实体运动测试。

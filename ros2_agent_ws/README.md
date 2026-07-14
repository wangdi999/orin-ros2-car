# ROS2 Agent Workspace

该工作空间是 LangGraph 车端编排方案的确定性 ROS2 执行层，目标环境为 Ubuntu 20.04 + ROS2 Foxy。

包含：

- `car_agent_interfaces`：Agent 工作区专用的任务、告警、状态和 Service 契约。
- `car_patrol`：旧版顺序巡检实现，仅保留用于兼容和逻辑测试。
- `car_safety`：旧版仲裁实现，仅保留用于兼容和逻辑测试，不进入默认启动图。
- `car_bringup`：兼容 Launch；默认不启动旧版 safety/patrol，避免产生第二个 `/cmd_vel` 发布者。

集成部署以 `ros2_car_remote_ws` 的 `icar_navigation` 启动图为准，只有
`cmd_vel_arbiter` 可以作为常规 `/cmd_vel` 发布者。Agent runtime 默认保持非硬件
编排层；`car_gateway` ROS 适配器不会由默认启动图启用。

构建：

```bash
cd ros2_agent_ws
source /opt/ros/foxy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

本仓库不包含完整 Nav2、SLAM、相机和实车依赖。只有在车端 Foxy 容器中完成 Topic、Action、TF 和设备确认后，才可进行实体运动测试。

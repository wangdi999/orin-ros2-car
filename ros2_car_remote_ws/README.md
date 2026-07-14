# ROS2 Remote-Control Workspace Extract

This is a partial ROS2 workspace containing remote-control related packages only.

Packages:

- `src/icar_ctrl`: keyboard and joystick teleop nodes.
- `src/icar_bringup`: chassis driver and bringup reference package.

Important limitation:

`icar_bringup` launch files reference packages that are expected to exist on the car Docker image, including `icar_description`, `icar_base_node`, `robot_localization`, `imu_filter_madgwick`, `joint_state_publisher`, and `robot_state_publisher`. This folder is therefore best treated as source reference and patch material unless it is placed back into the full car workspace.

On the car or in a ROS2 Foxy environment:

```bash
cd /root/icar_ros2_ws/icar_ws
source /opt/ros/foxy/setup.bash
colcon build --packages-select icar_ctrl icar_bringup
source install/setup.bash
```

Manual keyboard teleop:

```bash
ros2 run icar_ctrl icar_keyboard
```

Joystick stack:

```bash
ros2 launch icar_ctrl icar_joy_launch.py
ros2 run icar_ctrl icar_joy_X3
```

Always publish a zero Twist after motion tests.

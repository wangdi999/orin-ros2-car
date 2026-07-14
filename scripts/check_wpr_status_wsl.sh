#!/usr/bin/env bash
set -u

set +u
source /opt/ros/humble/setup.bash
if [ -f "${HOME}/ros2_ws/install/setup.bash" ]; then
  source "${HOME}/ros2_ws/install/setup.bash"
fi
set -u

echo "== ros env =="
env | grep '^ROS_' || true

echo "== package prefixes =="
for pkg in wpr_simulation2 gazebo_ros nav2_bringup slam_toolbox teleop_twist_keyboard xacro; do
  printf '%s: ' "${pkg}"
  ros2 pkg prefix "${pkg}" 2>&1 || true
done

echo "== workspace dirs =="
find "${HOME}/ros2_ws" -maxdepth 2 -type d -name 'wpr_simulation2' -o -name install -o -name build -o -name log 2>/dev/null

echo "== colcon latest logs =="
find "${HOME}/ros2_ws/log" -maxdepth 3 -type f -name '*.log' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 10

echo "== apt packages =="
dpkg -l \
  ros-humble-gazebo-ros-pkgs \
  ros-humble-gazebo-plugins \
  ros-humble-slam-toolbox \
  ros-humble-teleop-twist-keyboard \
  ros-humble-navigation2 \
  ros-humble-nav2-bringup \
  ros-humble-ros2-control \
  ros-humble-ros2-controllers \
  ros-humble-gazebo-ros2-control \
  ros-humble-pcl-ros \
  ros-humble-xacro \
  python3-colcon-common-extensions \
  pcl-tools 2>/dev/null | sed -n '/^ii/p' || true

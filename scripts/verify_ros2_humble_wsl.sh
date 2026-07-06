#!/usr/bin/env bash
set -euo pipefail

echo "== identity =="
whoami
echo "${HOME}"

echo "== os =="
sed -n '1,8p' /etc/os-release

echo "== wsl config =="
cat /etc/wsl.conf

echo "== ros setup =="
set +u
source /opt/ros/humble/setup.bash
set -u
command -v ros2
ros2 --help | head -n 8

echo "== installed packages =="
dpkg -l ros-humble-desktop ros-dev-tools ros-humble-rqt-robot-steering ros-humble-turtlesim terminator | sed -n '/^ii/p'

echo "== ros packages smoke =="
ros2 pkg prefix turtlesim
ros2 pkg prefix rqt_robot_steering
ros2 pkg prefix demo_nodes_cpp

echo "== workspace =="
ls -ld "${HOME}/ros2_ws" "${HOME}/ros2_ws/src"

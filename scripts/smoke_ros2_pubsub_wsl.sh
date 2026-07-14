#!/usr/bin/env bash
set -euo pipefail

set +u
source /opt/ros/humble/setup.bash
set -u

rm -f /tmp/ros2_talker.log /tmp/ros2_topic_echo.log

timeout 12s ros2 run demo_nodes_cpp talker >/tmp/ros2_talker.log 2>&1 &
talker_pid=$!

sleep 5

timeout 15s ros2 topic echo /chatter std_msgs/msg/String --once >/tmp/ros2_topic_echo.log 2>&1 || true

kill "${talker_pid}" >/dev/null 2>&1 || true
wait "${talker_pid}" >/dev/null 2>&1 || true

echo "== talker log =="
sed -n '1,8p' /tmp/ros2_talker.log || true
echo "== topic echo log =="
sed -n '1,20p' /tmp/ros2_topic_echo.log || true

grep -q "Hello World" /tmp/ros2_topic_echo.log

echo "ROS2 pub/sub smoke test passed."

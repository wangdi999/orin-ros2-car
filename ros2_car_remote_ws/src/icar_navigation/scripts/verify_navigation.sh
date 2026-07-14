#!/usr/bin/env bash
set -euo pipefail

nodes="$(ros2 node list)"
for required in /amcl /controller_server /planner_server /bt_navigator; do
  if ! grep -qx "$required" <<<"$nodes"; then
    echo "Missing required navigation node: $required" >&2
    exit 2
  fi
done
if grep -qx /cartographer_node <<<"$nodes"; then
  echo "Cartographer must not run with AMCL navigation mode." >&2
  exit 3
fi

cmd_info="$(ros2 topic info /cmd_vel --verbose)"
if ! grep -q "Publisher count: 1" <<<"$cmd_info" || \
   ! grep -q "Node name: cmd_vel_arbiter" <<<"$cmd_info"; then
  echo "/cmd_vel does not have the single expected arbiter owner." >&2
  exit 4
fi

nav_info="$(ros2 topic info /cmd_vel_nav --verbose)"
if ! grep -q "Node name: controller_server" <<<"$nav_info"; then
  echo "Nav2 controller is not publishing /cmd_vel_nav." >&2
  exit 5
fi

ros2 action info /navigate_to_pose
set +e
tf_output="$(timeout 3 ros2 run tf2_ros tf2_echo map base_footprint 2>&1)"
set -e
if ! grep -Eq 'At time|Translation' <<<"$tf_output"; then
  echo "map -> base_footprint TF is unavailable." >&2
  echo "$tf_output" >&2
  exit 6
fi

echo "Navigation ownership and action checks passed; no goal was sent."

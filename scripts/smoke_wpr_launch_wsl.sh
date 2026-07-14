#!/usr/bin/env bash
set -euo pipefail

set +u
source /opt/ros/humble/setup.bash
source "${HOME}/ros2_ws/install/setup.bash"
set -u

rm -f /tmp/wpr_launch_smoke.log

timeout 25s ros2 launch wpr_simulation2 wpb_simple.launch.py >/tmp/wpr_launch_smoke.log 2>&1 || true

pkill -f gzserver >/dev/null 2>&1 || true
pkill -f gzclient >/dev/null 2>&1 || true

echo "== launch log head =="
sed -n '1,40p' /tmp/wpr_launch_smoke.log || true
echo "== launch log tail =="
tail -n 40 /tmp/wpr_launch_smoke.log || true

if grep -E "Package .* not found|executable .* not found|ModuleNotFoundError|Traceback|No module named" /tmp/wpr_launch_smoke.log; then
  exit 1
fi

echo "wpr_simulation2 launch smoke test reached startup without missing-package errors."

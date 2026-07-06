#!/usr/bin/env bash
set -u

echo "== processes =="
ps -ef | grep -E "apt|dpkg|setup_ros2|curl|wget" | grep -v grep || true

echo "== ros2 command =="
command -v ros2 || true

echo "== package state =="
dpkg -l ros-humble-desktop ros-dev-tools ros-humble-rqt-robot-steering ros-humble-turtlesim terminator 2>/dev/null | sed -n "/^ii/p" || true

echo "== apt history tail =="
tail -n 80 /var/log/apt/term.log 2>/dev/null || true

echo "== apt cache =="
du -sh /var/cache/apt/archives 2>/dev/null || true
find /var/cache/apt/archives -maxdepth 2 -type f -printf "%s %p\n" 2>/dev/null | sort -nr | head -n 20 || true

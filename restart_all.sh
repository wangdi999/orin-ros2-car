#!/bin/bash
# Jetson上一键重启：相机 + AI推理
set -e

echo "=== 清理旧进程 ==="
pkill -9 -f camera_direct 2>/dev/null || true
pkill -9 -f mjpeg_bridge 2>/dev/null || true
pkill -9 -f yolov8_inference 2>/dev/null || true
fuser -k /dev/video0 2>/dev/null || true
sleep 2
echo "OK"

echo "=== 启动相机 ==="
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32

nohup python3 /home/jetson/start_camera.py > /tmp/camera_direct.log 2>&1 &
CAM_PID=$!
echo "  PID: $CAM_PID"
sleep 5
tail -3 /tmp/camera_direct.log

echo "=== 验证话题 ==="
for i in $(seq 1 8); do
    if ros2 topic list 2>/dev/null | grep -q "color/image_raw"; then
        echo "  [OK] /camera/color/image_raw"
        timeout 4 ros2 topic hz /camera/color/image_raw 2>&1 || true
        break
    fi
    echo "  等待 ($i/8)..."
    sleep 2
done

echo "=== 启动AI推理 ==="
source /home/jetson/smart_car_ws/install/setup.bash 2>/dev/null
nohup python3 /home/jetson/smart_car_ws/src/car_ai_vision/car_ai_vision/yolov8_inference.py > /tmp/ai_inference.log 2>&1 &
AI_PID=$!
echo "  PID: $AI_PID"
sleep 12
tail -8 /tmp/ai_inference.log | grep -v "WARNING\|deprecated\|np.bool"

echo ""
echo "=== 运行中 ==="
echo "  Camera: $CAM_PID (日志 /tmp/camera_direct.log)"
echo "  AI:     $AI_PID (日志 /tmp/ai_inference.log)"

#!/bin/bash
# ========================================
# 在Jetson主机上启动相机桥接+AI推理
# 用法: 将此脚本上传到Jetson后执行
#   scp start_bridge_on_jetson.sh jetson@192.168.160.196:~/
#   ssh jetson@192.168.160.196
#   bash ~/start_bridge_on_jetson.sh
# ========================================
set -e

source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32
export PYTHONPATH=/home/jetson/smart_car_ws/src/car_ai_vision:$PYTHONPATH

echo "=== 停止旧进程 ==="
pkill -f mjpeg_bridge 2>/dev/null || true
pkill -f yolov8_inference 2>/dev/null || true
sleep 1
echo "OK"

echo "=== 启动 mjpeg_bridge (相机→ROS2) ==="
nohup python3 /home/jetson/smart_car_ws/src/car_ai_vision/car_ai_vision/mjpeg_bridge.py > /tmp/mjpeg_bridge.log 2>&1 &
BRIDGE_PID=$!
echo "  PID=$BRIDGE_PID"

# 等待bridge启动
sleep 4

echo "=== 检查 /camera/color/image_raw ==="
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32
if ros2 topic list 2>/dev/null | grep -q "color/image_raw"; then
    echo "  [OK] 图像话题已就绪"
    ros2 topic hz /camera/color/image_raw --window 5 2>&1 | head -5 || true
else
    echo "  [FAIL] 图像话题未出现，检查日志:"
    cat /tmp/mjpeg_bridge.log
    exit 1
fi

echo ""
echo "=== 启动 yolov8_inference (AI推理) ==="
nohup python3 /home/jetson/smart_car_ws/src/car_ai_vision/car_ai_vision/yolov8_inference.py > /tmp/ai_inference.log 2>&1 &
AI_PID=$!
echo "  PID=$AI_PID"
sleep 5

echo "=== AI推理状态 ==="
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32
echo "  AI话题:"
ros2 topic list 2>/dev/null | grep -E "ai_alarm|ai_detections" || echo "  (等待中...)"

echo ""
echo "  AI日志 (最近10行):"
tail -10 /tmp/ai_inference.log 2>/dev/null || echo "  (无日志)"

echo ""
echo "=== 系统运行中 ==="
echo "  Bridge PID: $BRIDGE_PID  (日志: /tmp/mjpeg_bridge.log)"
echo "  AI PID:     $AI_PID    (日志: /tmp/ai_inference.log)"
echo ""
echo "  按 Ctrl+C 停止..."

# 等待
trap "kill $BRIDGE_PID $AI_PID 2>/dev/null; echo '已停止'" INT TERM
wait

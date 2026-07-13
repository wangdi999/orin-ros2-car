#!/bin/bash
# ==========================================
# 一键修复：释放相机 → 启动ROS2发布 → 启动AI推理
# 在 Jetson 上执行: bash ~/fix_all.sh
# ==========================================
set -e

echo "=== Step 1: 释放相机设备 ==="
kill 4095 2>/dev/null || true
pkill -f mjpeg_bridge 2>/dev/null || true
pkill -f yolov8_inference 2>/dev/null || true
sleep 2
echo "OK"

echo "=== Step 2: 启动直接相机ROS2发布 ==="
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32

nohup python3 -c "
import cv2, time, sys
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

rclpy.init()
node = Node('camera_direct')
pub = node.create_publisher(Image, '/camera/color/image_raw', 10)
bridge = CvBridge()

# Open camera
for attempt in range(5):
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        break
    print(f'Attempt {attempt+1}/5: waiting for /dev/video0...')
    time.sleep(1)

if not cap.isOpened():
    node.get_logger().error('FATAL: cannot open /dev/video0')
    sys.exit(1)

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 15)

ret, frame = cap.read()
if not ret:
    node.get_logger().error('FATAL: cannot read frame')
    sys.exit(1)

node.get_logger().info(f'Camera ready: {frame.shape}')
count = 0
while rclpy.ok():
    ret, frame = cap.read()
    if not ret:
        node.get_logger().warn('Frame read failed', throttle_duration_sec=5.0)
        time.sleep(0.1)
        continue
    msg = bridge.cv2_to_imgmsg(frame, encoding='bgr8')
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.header.frame_id = 'camera_color_frame'
    msg.height = 480
    msg.width = 640
    pub.publish(msg)
    count += 1
    if count % 30 == 0:
        node.get_logger().info(f'Published {count} frames')
    time.sleep(1.0 / 15.0)

cap.release()
node.destroy_node()
rclpy.shutdown()
" > /tmp/camera_direct.log 2>&1 &
CAM_PID=$!
echo "  Camera PID: $CAM_PID"
sleep 5

echo "=== Step 3: 验证图像话题 ==="
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32

# 先看相机日志判断相机是否成功
echo "  [相机日志]"
tail -5 /tmp/camera_direct.log

# 等待话题出现(最多15秒)
for i in $(seq 1 8); do
    if ros2 topic list 2>/dev/null | grep -q "color/image_raw"; then
        echo "  [OK] /camera/color/image_raw 已就绪"
        timeout 4 ros2 topic hz /camera/color/image_raw 2>&1 || true
        break
    fi
    echo "  等待中... ($i/8)"
    sleep 2
done

if ! ros2 topic list 2>/dev/null | grep -q "color/image_raw"; then
    echo "  [FAIL] 话题未出现，完整相机日志:"
    cat /tmp/camera_direct.log
    echo ""
    echo "  [提示] 手动检查: source /opt/ros/foxy/setup.bash && export ROS_DOMAIN_ID=32"
    echo "         ros2 topic list | grep image"
    exit 1
fi

echo ""
echo "=== Step 4: 启动AI推理节点 ==="
source /opt/ros/foxy/setup.bash
source /home/jetson/smart_car_ws/install/setup.bash 2>/dev/null
export ROS_DOMAIN_ID=32

nohup python3 /home/jetson/smart_car_ws/src/car_ai_vision/car_ai_vision/yolov8_inference.py > /tmp/ai_inference.log 2>&1 &
AI_PID=$!
echo "  AI PID: $AI_PID"
sleep 8

echo "=== Step 5: 验证AI话题 ==="
source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32
ros2 topic list | grep -E "ai_alarm|ai_detections" && echo "  [OK] AI话题已就绪" || echo "  [WARN] AI话题未出现"

echo ""
echo "=== AI推理日志 ==="
tail -15 /tmp/ai_inference.log
echo ""
echo "=== 系统运行中 ==="
echo "  Camera PID: $CAM_PID"
echo "  AI PID:     $AI_PID"
echo "  日志: tail -f /tmp/ai_inference.log"
echo "  按 Ctrl+C 停止所有..."
trap "kill $CAM_PID $AI_PID 2>/dev/null; echo Stopped" INT TERM
wait

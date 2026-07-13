"""直接OpenCV相机→ROS2发布节点"""
import cv2, time
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge

rclpy.init()
node = Node('camera_direct')
pub = node.create_publisher(Image, '/camera/color/image_raw', 10)
bridge = CvBridge()

# 重试打开相机
for i in range(10):
    cap = cv2.VideoCapture(0)
    if cap.isOpened():
        break
    time.sleep(0.5)

cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

ret, frame = cap.read()
if not ret:
    node.get_logger().error('Cannot read frame from /dev/video0')
    raise SystemExit(1)

node.get_logger().info(f'Camera OK: {frame.shape}')
count = 0

while rclpy.ok():
    ret, frame = cap.read()
    if not ret:
        time.sleep(0.05)
        continue
    msg = bridge.cv2_to_imgmsg(frame, encoding='bgr8')
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.header.frame_id = 'camera_color_frame'
    msg.height = 480
    msg.width = 640
    pub.publish(msg)
    rclpy.spin_once(node, timeout_sec=0.001)  # 必须spin才能实际发送！
    count += 1
    if count % 30 == 0:
        node.get_logger().info(f'Frames: {count}')
    time.sleep(1.0 / 15.0)

# CLAUDE.md — 智能小车项目

## 项目概述

基于 Jetson Orin Nano 4GB 的 ROS2 智能小车，实现**实时人员检测 + 异常行为识别** + Web远程控制 + SLAM导航。

成员B（AI算法工程师）负责 YOLOv8-TensorRT 边缘推理节点。

## 硬件

| 项目 | 值 |
|:---|:---|
| 型号 | Jetson Orin Nano **4GB**（~3.2GB可用） |
| JetPack | R35.3.1 (5.1.1), Ubuntu 20.04 aarch64 |
| CUDA | 11.4 |
| TensorRT | 8.5.2.2 |
| PyTorch | 2.1.0 (NVIDIA定制版) |
| Python | **3.8.10**（⚠️ 不支持3.9+语法） |
| 相机 | Orbbec Astra (USB: 2bc5:050f/060f) |
| 底盘 | 麦克纳姆轮全向 |

## 连接信息

| 参数 | 值 |
|:---|:---|
| Wi-Fi | `ohcar9` |
| IP | 由 `smart-car-console/local-config.json` 或运行参数提供（以小车屏幕 `MY_IP` 为准） |
| SSH | 用户名、密码和主机密钥仅保存在本地配置或实验室交接资料中 |
| ROS_DOMAIN_ID | **32** |
| Docker 容器 | `smartcar_icar_console` |
| Docker 镜像 | `icar/ros-foxy:1.0.2` |

## 架构

```
Jetson 主机 (GPU直通)
├── start_camera.py     — OpenCV读/dev/video0 → /camera/color/image_raw
├── yolov8_inference    — TensorRT推理 → /chassis/ai_alarm + /camera/ai_detections
│   ├── abnormal_behavior  — 规则引擎（宽高比+静止+深度）
│   ├── alarm_manager      — 消抖状态机（person:30s, abnormal:10s）
│   ├── capture_manager    — 异常截帧（前后30帧）
│   └── visualizer         — 检测框叠加
│
Docker smartcar_icar_console (ROS_DOMAIN_ID=32)
├── Mcnamu_driver_X3   — 底盘驱动 /cmd_vel
├── sllidar_ros2       — 激光雷达 /scan
├── rosbridge_server   — WebSocket :9090 ↔ 前端
└── MJPEG :6500        — 相机视频流（可能损坏，用start_camera.py替代）
```

## 关键目录

```
本地 (Windows):
  smart_car_ws/src/car_ai_vision/   — AI推理代码
  smart_car_ws/src/car_interfaces/  — ROS2消息定义(Alarm.msg)
  smart_car_ws/models/              — 模型文件(本地为空，在Jetson上)
  start_camera.py                   — 直接相机发布脚本
  fix_all.sh / restart_all.sh       — 部署脚本
  wddocs/                           — 开发文档
  docs/DEBUG_LOG_2026-07-12.md     — 调试日志
  smart-car-console/                — Web控制台

Jetson (~/smart_car_ws/):
  src/car_ai_vision/     — 已编译AI代码
  src/car_interfaces/    — 已编译消息包
  models/yolov8s.engine  — TensorRT FP16 (24MB)
  models/yolov8s.onnx    — ONNX降级 (44MB)
  install/               — colcon编译产物
```

## 一键启动（最新可用方案）

```bash
# SSH到Jetson后执行:
pkill -9 -f camera_direct; pkill -9 -f yolov8_inference; sleep 2

source /opt/ros/foxy/setup.bash
export ROS_DOMAIN_ID=32

# 1. 相机
nohup python3 ~/start_camera.py > /tmp/camera_direct.log 2>&1 &
sleep 5

# 2. AI推理
source ~/smart_car_ws/install/setup.bash
nohup python3 ~/smart_car_ws/src/car_ai_vision/car_ai_vision/yolov8_inference.py > /tmp/ai_inference.log 2>&1 &

# 3. 验证
sleep 12
source /opt/ros/foxy/setup.bash && export ROS_DOMAIN_ID=32
timeout 3 ros2 topic hz /camera/ai_detections   # 应有~12Hz
```

## ⚠️ 踩坑速查（修改代码前必读）

### 🚨 致命级
1. **`pub.publish()` 后必须 `rclpy.spin_once(node, timeout_sec=0.001)`**
   否则消息永远停在DDS队列不发送。话题存在但无数据流。

2. **numpy + TensorRT 8.5 兼容性**
   ```python
   import numpy as np
   np.bool = bool    # 必须在import tensorrt之前
   ```

3. **`source /opt/ros/foxy/setup.bash` 必须**
   否则 `import rclpy` → `ModuleNotFoundError`

### ⚠️ 重要级
4. **Python 3.8 类型注解** — 用 `Tuple`, `List`, `Optional`，禁用 `tuple[...]`, `list[...]`, `X | None`
5. **Jetson IP 可能 DHCP 变化** — 以屏幕 `MY_IP` 为准
6. **模型导出** — `.pt` → `.engine` 直接转换，不能 ONNX 中转（ultralytics 8.2.87）
7. **Jetson 4GB OOM** — 导出模型时 `workspace=2.0GB`（默认4GB会OOM）
8. **FPS ~12** — Orin Nano 4GB 上 YOLOv8s TensorRT 实测，属正常，阈值已设10

### 📌 常规级
9. 代码规范：`print()`→`self.get_logger()`, flake8 E9/F63/F7/F82 零容忍
10. 退出时释放 GPU 上下文 + 模型句柄 + 显存
11. 深度话题暂不可用 → 异常检测器自动降级（`depth_ok=True`）
12. OpenCV 无法用 `VideoCapture(url)` 读 MJPEG → 用 `requests` + `cv2.imdecode`

## 常用诊断命令

```bash
# 进程
ps aux | grep -E "camera_direct|yolov8"

# 话题
source /opt/ros/foxy/setup.bash && export ROS_DOMAIN_ID=32
ros2 topic list | grep -E "color|ai_alarm|ai_detect"
ros2 topic hz /camera/ai_detections
ros2 topic echo /chassis/ai_alarm

# Docker
docker ps --filter name=smartcar
docker exec smartcar_icar_console ros2 topic list

# 日志
tail -f /tmp/ai_inference.log
tail -f /tmp/camera_direct.log
```

## 通信流程

```
相机 → start_camera.py → /camera/color/image_raw (ROS2)
  → yolov8_inference → TensorRT推理
    → /chassis/ai_alarm (person_detected | abnormal_behavior)
    → /camera/ai_detections (可视化帧)
      → llm_decision (Docker内) / Web前端
```

## 模型

- YOLOv8-small, COCO预训练, `person` 类 (class_id=0)
- 置信度阈值: 0.5
- TensorRT FP16: ~12 FPS @ 640×480 on Orin Nano 4GB
- 异常行为: 宽高比>1.5 + 15帧静止 + 深度方差<0.3 (AND)

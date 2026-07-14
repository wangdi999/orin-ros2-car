#!/bin/bash
# ============================================================
# start_ai_viewer.sh - AI检测可视化独立启动脚本
#
# 用法：
#   bash start_ai_viewer.sh              # 默认端口6501
#   bash start_ai_viewer.sh 6502         # 指定端口
#
# 启动后在浏览器打开 http://<jetson_ip>:<端口>/
# ============================================================

set -e

PORT=${1:-6501}

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- 环境检查 ----
if ! command -v ros2 &> /dev/null; then
    source /opt/ros/foxy/setup.bash 2>/dev/null || {
        log_error "ROS2 Foxy 未找到，请先 source /opt/ros/foxy/setup.bash"
        exit 1
    }
fi

export ROS_DOMAIN_ID=32
log_info "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"

# ---- 检查工作空间 ----
WS_SETUP="$HOME/smart_car_ws/install/setup.bash"
if [ -f "$WS_SETUP" ]; then
    source "$WS_SETUP"
    log_info "已 source: $WS_SETUP"
else
    log_error "工作空间未编译: $WS_SETUP"
    log_error "请先运行: cd ~/smart_car_ws && colcon build --packages-select car_ai_vision"
    exit 1
fi

# ---- 检查话题就绪 ----
log_info "检查 ROS2 话题..."

TOPIC_LIST=$(timeout 5 ros2 topic list 2>/dev/null || true)

if echo "$TOPIC_LIST" | grep -qF "/camera/ai_detections"; then
    log_info "/camera/ai_detections 已就绪"
else
    log_warn "/camera/ai_detections 未就绪（等待推理节点启动）"
    log_warn "如果仪表盘无画面，请先启动推理节点："
    log_warn "  ros2 run car_ai_vision yolov8_inference"
fi

if echo "$TOPIC_LIST" | grep -qF "/chassis/ai_alarm"; then
    log_info "/chassis/ai_alarm 已就绪"
else
    log_warn "/chassis/ai_alarm 未就绪（报警功能暂不可用）"
fi

# ---- 获取本机IP ----
MY_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$MY_IP" ]; then
    MY_IP=$(ip addr show 2>/dev/null | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}' | cut -d/ -f1)
fi
if [ -z "$MY_IP" ]; then
    MY_IP="<jetson_ip>"
fi

# ---- 启动 ----
log_info "启动 AI Web Bridge (端口: $PORT)..."
echo ""
echo "  ============================================"
echo "  AI检测可视化仪表盘"
echo "  ============================================"
echo "  仪表盘:   http://${MY_IP}:${PORT}/"
echo "  视频流:   http://${MY_IP}:${PORT}/video_feed"
echo "  报警API:  http://${MY_IP}:${PORT}/api/alarms"
echo "  性能API:  http://${MY_IP}:${PORT}/api/perf"
echo "  ============================================"
echo ""
echo "  按 Ctrl+C 停止"
echo ""

ros2 run car_ai_vision ai_web_bridge --ros-args -p port:=$PORT

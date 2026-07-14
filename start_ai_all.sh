#!/bin/bash
# ============================================================
# start_ai_all.sh — AI模块一键启动（相机 + 推理 + 可视化）
# 用法: bash ~/start_ai_all.sh
# 停止: bash ~/start_ai_all.sh --stop
# ============================================================

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ---- 停止模式 ----
if [ "$1" = "--stop" ] || [ "$1" = "-s" ]; then
    log_info "停止所有AI模块..."
    pkill -9 -f camera_direct   2>/dev/null && log_info "相机 已停止" || true
    pkill -9 -f yolov8_inference 2>/dev/null && log_info "推理 已停止" || true
    pkill -9 -f ai_web_bridge    2>/dev/null && log_info "可视化 已停止" || true
    log_info "全部已停止"
    exit 0
fi

# ---- 启动模式 ----
log_info "=== AI模块一键启动 ==="

# 1. 停旧进程
log_info "清理旧进程..."
pkill -9 -f camera_direct   2>/dev/null || true
pkill -9 -f yolov8_inference 2>/dev/null || true
pkill -9 -f ai_web_bridge    2>/dev/null || true
sleep 2

# 2. 环境
source /opt/ros/foxy/setup.bash
source ~/smart_car_ws/install/setup.bash 2>/dev/null || log_warn "workspace未编译"
export ROS_DOMAIN_ID=32

# 3. 相机
log_info "启动相机..."
nohup python3 ~/start_camera.py > /tmp/camera_direct.log 2>&1 &
CAM_PID=$!
log_info "  相机 PID: $CAM_PID"
sleep 5

# 4. AI推理
log_info "启动AI推理..."
nohup python3 ~/smart_car_ws/src/car_ai_vision/car_ai_vision/yolov8_inference.py \
    > /tmp/ai_inference.log 2>&1 &
AI_PID=$!
log_info "  推理 PID: $AI_PID"
sleep 8

# 5. 可视化桥接
log_info "启动可视化桥接..."
nohup python3 ~/smart_car_ws/install/car_ai_vision/bin/ai_web_bridge \
    > /tmp/ai_web_bridge.log 2>&1 &
WEB_PID=$!
log_info "  可视化 PID: $WEB_PID"
sleep 3

# 6. 状态
log_info "=== 全部启动完成 ==="
echo ""
echo "  进程:"
echo "    相机:     $CAM_PID"
echo "    AI推理:   $AI_PID"
echo "    可视化:   $WEB_PID"
echo ""
echo "  日志:"
echo "    相机:     tail -f /tmp/camera_direct.log"
echo "    AI推理:   tail -f /tmp/ai_inference.log"
echo "    可视化:   tail -f /tmp/ai_web_bridge.log"
echo ""
echo "  仪表盘:  http://<jetson_ip>:6501/"
echo ""
echo "  停止:    bash ~/start_ai_all.sh --stop"
echo ""

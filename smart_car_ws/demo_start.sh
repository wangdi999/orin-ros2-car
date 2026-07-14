#!/bin/bash
# ============================================================
# demo_start.sh - 智能小车一键启动演示脚本
#
# 功能：
#   1. 检查并启动 Docker 容器（底盘 + 雷达 + 相机驱动）
#   2. 启动主机侧 AI 推理节点
#   3. 设置 ROS_DOMAIN_ID=32 实现跨 Docker DDS 通信
#
# 用法：
#   ./demo_start.sh              # 默认启动（WARN 日志级别）
#   ./demo_start.sh --debug      # DEBUG 模式（全量 INFO 日志）
#   ./demo_start.sh --no-docker  # 仅启动 AI 推理，不管理 Docker
#
# 运行位置：Jetson Orin Nano 主机
# ============================================================

set -e

# ---- 配置 ----
ROS_DOMAIN_ID=32
SMART_CAR_WS="$HOME/smart_car_ws"
MODEL_PATH="$SMART_CAR_WS/models/yolov8s.engine"
ONNX_PATH="$SMART_CAR_WS/models/yolov8s.onnx"
DOCKER_CONTAINER="smartcar_icar_console"

# ---- 颜色输出 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${BLUE}[STEP]${NC} $1"; }

# ---- 参数解析 ----
DEBUG_FLAG=""
NO_DOCKER=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)
            DEBUG_FLAG="--debug"
            shift
            ;;
        --no-docker)
            NO_DOCKER=true
            shift
            ;;
        --help|-h)
            echo "用法: $0 [--debug] [--no-docker]"
            echo ""
            echo "选项:"
            echo "  --debug      开启 DEBUG 模式（全量 INFO 日志）"
            echo "  --no-docker  仅启动 AI 推理，不管理 Docker"
            echo "  --help       显示此帮助信息"
            exit 0
            ;;
        *)
            log_error "未知参数: $1"
            exit 1
            ;;
    esac
done

# ---- 前置检查 ----
log_step "=== 环境检查 ==="

# 检查 ROS2 环境
if ! command -v ros2 &> /dev/null; then
    log_error "ros2 未找到，请先 source ROS2 环境"
    echo "  source /opt/ros/foxy/setup.bash"
    exit 1
fi
log_info "ROS2 已就绪: $(ros2 --version 2>&1 || true)"

# 检查 ROS_DOMAIN_ID
export ROS_DOMAIN_ID=$ROS_DOMAIN_ID
log_info "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"

# 检查工作空间
if [ ! -d "$SMART_CAR_WS" ]; then
    log_error "工作空间不存在: $SMART_CAR_WS"
    log_error "请先创建并编译工作空间"
    exit 1
fi

# Source 工作空间
WS_SETUP="$SMART_CAR_WS/install/setup.bash"
if [ -f "$WS_SETUP" ]; then
    source "$WS_SETUP"
    log_info "已 source: $WS_SETUP"
else
    log_warn "工作空间未编译，请先运行:"
    log_warn "  cd $SMART_CAR_WS && colcon build"
fi

# 检查模型文件（优先 engine，降级 onnx）
MODEL_READY=false
if [ -f "$MODEL_PATH" ]; then
    log_info "TensorRT engine 就绪: $MODEL_PATH"
    MODEL_READY=true
elif [ -f "$ONNX_PATH" ]; then
    log_warn "TensorRT engine 不存在，将使用 ONNX 降级"
    log_warn "建议运行 export_model.py 导出 TensorRT engine"
    log_info "ONNX 模型就绪: $ONNX_PATH"
    MODEL_READY=true
else
    log_error "模型文件不存在!"
    log_error "  TensorRT: $MODEL_PATH"
    log_error "  ONNX:     $ONNX_PATH"
    log_error "请先运行 export_model.py 导出模型"
    exit 1
fi

# ---- Docker 容器管理 ----
if [ "$NO_DOCKER" = false ]; then
    log_step "=== Docker 容器检查 ==="

    if command -v docker &> /dev/null; then
        CONTAINER_RUNNING=$(docker ps --filter "name=$DOCKER_CONTAINER" --format "{{.Names}}" 2>/dev/null || true)

        if [ -z "$CONTAINER_RUNNING" ]; then
            log_warn "Docker 容器 $DOCKER_CONTAINER 未运行"

            CONTAINER_EXISTS=$(docker ps -a --filter "name=$DOCKER_CONTAINER" --format "{{.Names}}" 2>/dev/null || true)
            if [ -n "$CONTAINER_EXISTS" ]; then
                log_info "启动已存在的容器..."
                docker start "$DOCKER_CONTAINER"
            else
                log_error "容器 $DOCKER_CONTAINER 不存在"
                log_error "请确保 Docker 容器已正确配置"
            fi
        else
            log_info "Docker 容器已运行: $DOCKER_CONTAINER"
        fi
    else
        log_warn "Docker 未安装或不在 PATH，跳过容器管理"
    fi
else
    log_info "跳过 Docker 管理（--no-docker）"
fi

# ---- 等待相机和底盘就绪 ----
log_step "=== 等待传感器就绪 ==="

# 等待话题出现
TIMEOUT=30
ELAPSED=0
REQUIRED_TOPICS=(
    "/camera/color/image_raw"
    "/camera/depth/image_raw"
    "/odom"
)

log_info "等待 ROS2 话题就绪（最长 ${TIMEOUT}s）..."
while [ $ELAPSED -lt $TIMEOUT ]; do
    ALL_READY=true
    TOPIC_LIST=$(ros2 topic list 2>/dev/null || true)

    for topic in "${REQUIRED_TOPICS[@]}"; do
        if ! echo "$TOPIC_LIST" | grep -qF "$topic"; then
            ALL_READY=false
            break
        fi
    done

    if [ "$ALL_READY" = true ]; then
        log_info "所有必需话题已就绪"
        break
    fi

    sleep 2
    ELAPSED=$((ELAPSED + 2))
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    log_warn "等待超时，部分话题可能未就绪"
    log_warn "当前话题列表:"
    ros2 topic list 2>/dev/null || log_warn "  (无法获取话题列表)"
fi

# ---- 启动 AI 推理节点 ----
log_step "=== 启动 AI 推理节点 ==="

if [ -n "$DEBUG_FLAG" ]; then
    log_info "模式: DEBUG（全量 INFO 日志）"
    ros2 run car_ai_vision yolov8_inference --ros-args -p debug:=true &
else
    log_info "模式: 生产（WARN+ 日志）"
    ros2 run car_ai_vision yolov8_inference &
fi

AI_PID=$!
log_info "AI 推理节点已启动 (PID: $AI_PID)"

# ---- 启动 AI Web Bridge ----
sleep 3  # 等待推理节点开始发布话题
ros2 run car_ai_vision ai_web_bridge &
WEB_PID=$!
log_info "AI Web Bridge 已启动 (PID: $WEB_PID)"

# ---- 运行状态监控 ----
log_step "=== 系统运行中 ==="
echo ""
echo "  Docker 容器:  $DOCKER_CONTAINER"
echo "  AI 推理 PID:  $AI_PID"
echo "  Web Bridge:    $WEB_PID"
echo "  ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
echo "  日志级别:      ${DEBUG_FLAG:+DEBUG}${DEBUG_FLAG:-WARN+}"
echo ""
echo "  话题监控:"
echo "    订阅: /camera/color/image_raw, /camera/depth/image_raw, /odom"
echo "    发布: /chassis/ai_alarm, /camera/ai_detections"
echo ""
echo "  AI可视化:  http://<jetson_ip>:6501 (浏览器直接查看)"
echo ""
echo "  按 Ctrl+C 停止所有服务"
echo ""

# ---- 清理函数 ----
cleanup() {
    echo ""
    log_step "=== 正在停止服务 ==="

    if [ -n "$WEB_PID" ] && kill -0 "$WEB_PID" 2>/dev/null; then
        log_info "停止 AI Web Bridge (PID: $WEB_PID)..."
        kill -TERM "$WEB_PID" 2>/dev/null || true
        wait "$WEB_PID" 2>/dev/null || true
        log_info "AI Web Bridge 已停止"
    fi

    if [ -n "$AI_PID" ] && kill -0 "$AI_PID" 2>/dev/null; then
        log_info "停止 AI 推理节点 (PID: $AI_PID)..."
        kill -TERM "$AI_PID" 2>/dev/null || true
        wait "$AI_PID" 2>/dev/null || true
        log_info "AI 推理节点已停止"
    fi

    log_info "演示已停止"
    exit 0
}

trap cleanup SIGINT SIGTERM

# ---- 等待推理节点退出 ----
wait "$AI_PID" 2>/dev/null || true
cleanup

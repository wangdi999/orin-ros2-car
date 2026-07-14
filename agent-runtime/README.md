# Agent Runtime

车端非实时智能编排服务。默认运行在安全的 `mock` 网关模式，不会连接实体底盘。

## 本地开发

```bash
cd agent-runtime
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
pytest
uvicorn car_agent.api.app:create_app --factory --port 8100
```

健康检查：

```bash
curl http://127.0.0.1:8100/health
```

除 `/health` 外，API 需要：

```text
Authorization: Bearer <CAR_AGENT_TOKEN>
```

## 安全限制

- `CAR_AGENT_GATEWAY_MODE=mock` 是默认值。
- 实车 rosbridge Service 名称、类型和状态 Topic 未确认前，服务会拒绝启用真实网关。
- Agent 不发布 `/cmd_vel`，急停和速度仲裁由 ROS2 Safety Supervisor 承担。
- `locations.yaml` 中未标定的地点必须保持 `enabled: false`。
- 自然语言运动默认限制为 `0.30 m`、`0.08 m/s` 和 `8 s`。需要扩大时必须在具体部署中显式设置 `CAR_AGENT_MOTION_MAX_DISTANCE_M`、`CAR_AGENT_MOTION_MAX_SPEED_MPS` 和 `CAR_AGENT_MOTION_MAX_DURATION_SEC`，宿主机运动网关也必须配置相同上限。

## 语音播报

Agent Runtime 支持把任务级状态发送到宿主机 TTS bridge，由宿主机调用小米 MiMo 并播放音频。默认关闭：

```text
TTS_ENABLED=false
TTS_BRIDGE_URL=http://127.0.0.1:8123/speak
TTS_TIMEOUT_SEC=2
```

在小车宿主机启动 bridge：

```bash
python3 scripts/mimo_tts_bridge.py --env-file agent-runtime/.env
```

bridge 会读取 `TTS_BASE_URL`/`TTS_API_KEY`，也可以复用 `LLM_BASE_URL`/`LLM_API_KEY`。默认模型是 `mimo-v2.5-tts`，默认音色是 `mimo_default`，默认只监听 `127.0.0.1:8123`。

## 语音输入

控制台可以把浏览器录音发送给 Agent Runtime，由 Runtime 调用小米 MiMo ASR 转写为文本。默认关闭：

```text
ASR_ENABLED=false
ASR_BASE_URL=
ASR_MODEL=mimo-v2.5-asr
ASR_API_KEY=
ASR_TIMEOUT_SEC=30
```

`ASR_BASE_URL`/`ASR_API_KEY` 为空时会复用 `LLM_BASE_URL`/`LLM_API_KEY`。语音输入只生成文本，不直接控制底盘；文本仍需经过运动指令解析、校验和人工确认。

## 真实 ROS 网关

默认仍使用 `CAR_AGENT_GATEWAY_MODE=mock`。接入真实 ROS 控制栈时，宿主机先启动 `car_gateway`：

```bash
source /opt/ros/foxy/setup.bash
source ~/orin-ros2-car/ros2_agent_ws/install/setup.bash
# 可选的旧版 ROS 适配器（默认集成部署不要启动）：
# ros2 launch car_gateway gateway_launch.py http_host:=127.0.0.1 http_port:=8130
```

Agent Runtime 再切到 HTTP 网关：

```text
CAR_AGENT_GATEWAY_MODE=http_rosbridge
ROS_GATEWAY_BASE_URL=http://127.0.0.1:8130
ROS_GATEWAY_TIMEOUT_SEC=3
```

HTTP 网关只暴露任务级接口：`/api/v1/patrol/create`、`/api/v1/patrol/control`、`/api/v1/robot/summary` 和 `/api/v1/safety/emergency-stop`。Agent 仍不直接发布 `/cmd_vel`。

`/api/v1/robot/summary` 会保守判定硬件状态：`chassis_online` 需要底盘驱动订阅 `/cmd_vel` 或发布 odom，`nav2_ready` 需要 `NavigateToPose` action server 的服务端接口存在。仅启动安全仲裁和巡检管理节点不会被当作底盘或 Nav2 已就绪。

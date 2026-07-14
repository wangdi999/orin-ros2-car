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

bridge 会读取 `TTS_BASE_URL`/`TTS_API_KEY`，也可以复用 `LLM_BASE_URL`/`LLM_API_KEY`。默认模型是 `mimo-v2.5-tts`，默认只监听 `127.0.0.1:8123`。

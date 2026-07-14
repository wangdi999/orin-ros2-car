# Data Model: ROS2 核心与导航四天闭环

**Date**: 2026-07-12
**Feature**: [spec.md](./spec.md)

## 1. MotionRequest

表示一个上游速度请求，ROS 传输类型为 `geometry_msgs/msg/Twist`，接收元数据由仲裁器本地维护。

| Field | Type | Validation |
|---|---|---|
| `source` | enum `MANUAL | NAVIGATION` | 由订阅入口决定，消息不能自报来源 |
| `received_monotonic_sec` | float | 单调时钟，必须有限且不倒退 |
| `linear_x` | float | 有限；仲裁软限制内 |
| `linear_y` | float | 有限；导航来源必须为 0 |
| `angular_z` | float | 有限；仲裁软限制内 |
| `fresh` | derived bool | 当前时刻减接收时刻不超过来源 timeout |

最终驱动再次执行独立硬限制：`|linear.x/y| ≤ 0.35`、`|angular.z| ≤ 0.80`。

## 2. ActiveSource

```text
NONE -> MANUAL
NONE -> NAVIGATION
MANUAL -> ZEROING -> NAVIGATION
NAVIGATION -> ZEROING -> MANUAL
ANY --low battery + authorized patrol status--> ZEROING -> RETURN_HOME
ANY -> BLOCKED
BLOCKED -> NONE       (only after explicit safety reset)
```

| State | Meaning | Allowed final output |
|---|---|---|
| `NONE` | 无新鲜请求 | 零 |
| `ZEROING` | 来源切换的强制零周期 | 零 |
| `MANUAL` | 人工请求新鲜且安全允许 | 限幅人工 Twist |
| `NAVIGATION` | 导航请求新鲜且安全允许 | 限幅导航 Twist，`linear.y=0` |
| `RETURN_HOME` | 安全状态为低电返航，且新鲜巡航状态为 `RETURN_HOME/NAVIGATING` | 仅限幅 `/cmd_vel_nav`，`linear.y=0` |
| `BLOCKED` | 急停或故障锁存 | 零 |

`LOW_BATTERY_RETURN` 不等于无条件放行导航。巡航状态超过 0.30 秒未更新、mode 不是 `RETURN_HOME`、state 不是 `NAVIGATING`，或出现任何其他锁存故障时，仲裁输出必须为零。

人工接管会锁存“旧导航禁止恢复”。人工命令随后超时也只能进入 `NONE`，不得重新选择仍在发布的旧 `/cmd_vel_nav`；只有显式启动的新巡航（状态从 `IDLE` 进入 `NAVIGATING`）或故障后的显式安全复位才能重新授权普通导航。

任何非零输出还要求 `/safety/state` 心跳不超过 0.30 秒；安全管理器退出或状态陈旧时，仲裁器进入 `BLOCKED` 并持续输出零。低电返航的 `/patrol/status` 授权同样采用 0.30 秒门槛，而不是依赖最后一次状态无限有效。

## 3. HealthSnapshot

安全管理器在单调时钟上计算的健康快照。

| Field | Source | Default freshness | Healthy condition |
|---|---|---:|---|
| `chassis_connected` | `/chassis/connected` | 0.30 s | 10 Hz 心跳最近状态为 true 且新鲜 |
| `scan_age_sec` | `/scan` header/receive time | 0.50 s | 至少 5 Hz 运行期且不陈旧 |
| `odom_age_sec` | `/odom` header/receive time | 0.20 s | 至少 20 Hz 运行期且不陈旧 |
| `tf_complete` | TF lookup | 0.20 s | `odom → base_footprint` 和传感器链可查 |
| `ownership_valid` | ROS graph + configured mode | 0.50 s | 最终速度、odom、scan 发布者数量/身份符合契约，且 AMCL/Cartographer 不共存 |
| `patrol_status_age_sec` | `/patrol/status` receive time | 0.30 s | 低电返航放行期间必须新鲜且为 `RETURN_HOME/NAVIGATING` |
| `estop_requested` | `/safety/estop` | latched | false |
| `voltage_average` | `/voltage` | 10 samples | 有限；只观察，默认不触发 |

启动宽限期内系统保持 `INITIALIZING` 和零速度，不把尚未出现的数据误记为运行期故障。

## 4. SafetyState

| State | Entry condition | Exit condition | Motion permission |
|---|---|---|---|
| `INITIALIZING` | 节点启动或健康窗口未填满 | 所有必需健康条件满足 | 禁止 |
| `READY` | 初始化完成或显式复位成功 | 任一锁存条件出现 | 允许仲裁后的请求 |
| `ESTOP` | 急停输入为 true | 急停解除、健康且显式复位 | 禁止 |
| `CHASSIS_FAULT` | 底盘断连或状态陈旧 | 连接恢复、健康且显式复位 | 禁止 |
| `SENSOR_FAULT` | 激光陈旧/缺失 | 激光恢复、健康且显式复位 | 禁止 |
| `ODOM_TF_FAULT` | odom 陈旧或 TF 缺失/冲突 | 链路恢复、健康且显式复位 | 禁止 |
| `OWNERSHIP_FAULT` | 关键 topic 发布者数量/身份错误，或 AMCL 与 Cartographer 冲突 | 冲突消失、健康且显式复位 | 禁止 |
| `LOW_BATTERY_RETURN` | 模拟触发或启用后的真实阈值满足 | 到达 Home 或返航失败 | 仅在新鲜 `RETURN_HOME/NAVIGATING` 握手下允许返航来源 |
| `RETURNED_HOME` | 低电返航成功 | 健康且显式复位 | 禁止 |
| `RETURN_FAILED` | 低电返航失败/超时 | 健康、人工处理且显式复位 | 禁止 |

规则：锁存状态不会因为 topic 恢复自动转成 `READY`；复位必须验证故障源消失、最终输出为零且不存在活动自主 action。低电触发时，安全管理器先进入 `LOW_BATTERY_RETURN` 并使普通来源归零；巡航管理器观察该状态、取消原 goal、进入 `RETURN_HOME`，仲裁器只在状态握手新鲜后放行返航。Home 成功或失败通过 `/patrol/status.reason` 回传给安全管理器。

## 5. Alarm

ROS 传输由 `car_interfaces/msg/Alarm` 定义。

| Field | Type | Rules |
|---|---|---|
| `header` | `std_msgs/Header` | 事件时间和公共 frame（无 frame 时为空） |
| `severity` | uint8 | `INFO=0`, `WARNING=1`, `ERROR=2`, `CRITICAL=3` |
| `code` | string | 稳定大写 snake case，例如 `CHASSIS_DISCONNECTED` |
| `source` | string | 发布节点或子系统 |
| `state` | string | 触发后的安全/巡航状态 |
| `message` | string | 面向操作者的简短说明，不含凭据 |
| `active` | bool | true 表示激活，false 表示清除记录 |

同一 `(source, code)` 的重复活动告警应去重；状态改变或固定节流周期后才可重发。

## 6. Waypoint and Route

### Waypoint

| Field | Type | Validation |
|---|---|---|
| `name` | string | 非空，在 route 内唯一 |
| `x`, `y` | float | 有限，来自最终地图实测 |
| `yaw` | float | 有限，规范化到 `[-pi, pi]` |
| `dwell_sec` | optional float | `≥ 0`；省略时继承 route 默认值 |

### Route

| Field | Type | Validation |
|---|---|---|
| `configured` | bool | 必须为 true 才允许运动启动；false 模板的坐标允许为 null，切换 true 后所有坐标必须为有限数 |
| `frame_id` | string | 本功能固定为 `map` |
| `home` | Waypoint | 必须存在且唯一；未配置模板使用 null 坐标而不是可误执行的零坐标 |
| `waypoints` | list[Waypoint] | D3 实车验收必须恰有 3 个；未配置模板坐标为 null |
| `default_dwell_sec` | float | 默认 3，`≥ 0` |
| `max_retries` | int | 默认 1，范围 0..3 |
| `failure_policy` | enum | 本轮支持 `skip | abort`，默认 `skip` |
| `loop` | bool | 默认 false |

## 7. PatrolRun

| Field | Type | Meaning |
|---|---|---|
| `run_id` | string | 本地唯一执行标识 |
| `mode` | `PATROL | RETURN_HOME` | 目标序列来源 |
| `state` | PatrolState | 当前状态 |
| `waypoint_index` | int | 当前航点；返航时为 -1 |
| `attempt` | int | 当前目标从 0 开始的重试次数 |
| `route_configured` | bool | Home 与三个航点是否均已通过有限坐标校验 |
| `goal_started_monotonic_sec` | float? | action 超时基准 |
| `termination_reason` | string? | completed/cancelled/manual/fault/timeout 等 |

### PatrolState transitions

```text
IDLE --start(valid route, safety READY)--> NAVIGATING
NAVIGATING --goal succeeded-------------> ARRIVED
ARRIVED --------------------------------> WAITING
WAITING --dwell elapsed-----------------> NEXT_GOAL
NEXT_GOAL --more goals------------------> NAVIGATING
NEXT_GOAL --route complete--------------> IDLE
NAVIGATING --failure, retry available---> NAVIGATING
NAVIGATING --failure, skip policy-------> NEXT_GOAL
ANY ACTIVE --cancel/manual/fault--------> CANCELLING -> IDLE
ANY ACTIVE --low battery----------------> CANCELLING -> RETURN_HOME -> NAVIGATING
RETURN_HOME --success-------------------> IDLE + Safety RETURNED_HOME
RETURN_HOME --failure-------------------> IDLE + Safety RETURN_FAILED
```

动作结果规则：Foxy `NavigateToPose.Result` 的 `result` 内容为空；只有 goal handle、action status、取消结果、超时和本地尝试记录决定转换。

## 8. MapArtifactSet

| Field | Type | Rules |
|---|---|---|
| `basename` | string | 本轮固定 `campus_map` |
| `pgm_path` | path | 栅格数据，必须与 YAML image 引用一致 |
| `yaml_path` | path | resolution/origin/threshold 可解析 |
| `pbstream_path` | path | 与同一建图会话生成 |
| `landmark_measurements` | list[5] | 每个地图/现场误差 `≤ 0.20 m` |
| `reload_results` | list[2] | 两次均成功 |

## 9. AcceptanceEvidence

| Field | Type | Rules |
|---|---|---|
| `gate` | `D1 | D2 | D3 | D4` | 必填 |
| `case_id` | string | 与 tasks/checklist 对应 |
| `started_at`, `ended_at` | timestamp | 必填 |
| `preconditions` | list[string] | 包括场地安全确认（若运动） |
| `observations` | mapping | topic rate、publisher、action、误差等 |
| `stop_latency_sec` | optional float | 故障运动测试必填 |
| `result` | `PASS | FAIL | BLOCKED` | 不允许静默跳过 |
| `recovery` | string | 恢复步骤和结果 |
| `artifact_paths` | list[path] | 只引用忽略目录或小型已提交摘要 |

原始 rosbag、SSH 输出中的凭据和大体积日志不得成为提交文件。

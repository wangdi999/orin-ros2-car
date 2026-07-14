# LangGraph 车端编排开发分析与实施状态

## 1. 文档结论

需求分析和详细设计共同限定了一个明确的安全边界：

- LLM 只负责自然语言理解、结构化计划、告警解释和报告生成。
- LangGraph 只负责任务级工作流、人工确认、事件分支和恢复。
- Patrol Manager、Nav2、Safety Supervisor 和底盘驱动负责确定性执行。
- 急停、Watchdog、速度限幅和危险暂停不得依赖云端模型。
- LLM 只能选择预登记的地点 ID，禁止生成坐标、速度、任意 ROS2 Topic 或 Shell 命令。

第一版核心闭环为：

```text
自然语言任务
→ 结构化计划
→ 本地校验
→ 人工确认
→ Patrol Manager 顺序导航
→ 任务/告警事件回传
→ LangGraph 恢复工作流
→ 报告
```

## 2. 现有仓库与设计文档的差距

现有仓库已具备：

- React + Node.js 控制台。
- rosbridge 连接与 `/cmd_vel` 遥控。
- 键盘、摇杆、视频、遥测和急停。
- `Mcnamu_driver_X3` 底盘驱动参考。

当前缺失：

- Agent Runtime、LangGraph、LLM Provider 和持久化数据库。
- 命名地点与计划校验。
- Patrol Manager、任务状态机和 Nav2 Action Client。
- 控制源仲裁与独立 Safety Supervisor。
- ROS2 自定义消息和 Service。
- 任务事件、告警和报告 API。
- 控制台到 Agent 的安全代理与新界面。

## 3. 本分支实施范围

`devcp` 首轮开发采用“先确定性、后智能”的顺序：

1. 建立 `agent-runtime` 基础工程、配置、数据库、Plan Schema、校验器和 Mock Robot Gateway。
2. 建立 ROS2 `car_interfaces`、`car_patrol`、`car_safety` 和 `car_bringup` 包骨架。
3. 保留现有 `/cmd_vel` 驱动边界，不执行任何物理运动测试。
4. 增加 Node.js Agent 反向代理，浏览器不持有车端高权限 Token。
5. 增加单元测试，确保未知地点、非法策略、急停和任务冲突被拒绝。

## 4. 实车联调前必须确认

- ROS2 容器真实镜像和 Tag。
- Nav2 Action 名称与生命周期状态。
- `/cmd_vel` 是否可重映射为 `/cmd_vel_nav`。
- 启用 Safety Supervisor 时，将控制台 `control.commandTopic` 设置为 `/cmd_vel_teleop`；
  未启用时保留 `/cmd_vel` 兼容现有遥控链路。
- 相机 Topic、TF 树和地图 Frame。
- rosbridge 对自定义 Service 的调用能力。
- 实际地图与命名地点坐标。
- YOLO 类别、模型和截图路径。

未确认上述信息前，代码默认使用 Mock Gateway 和保守配置，不向实体底盘发送运动指令。

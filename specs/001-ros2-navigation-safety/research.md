# Research: ROS2 核心与导航四天闭环

**Date**: 2026-07-12
**Target runtime inspected**: ROS 2 Foxy at the physical car; current test endpoint updated to `192.168.43.137`.

## R1. Final velocity boundary

**Decision**: 控制台发布 `/cmd_vel_manual`，Nav2 controller 输出重映射为 `/cmd_vel_nav`，`cmd_vel_arbiter` 独占 `/cmd_vel`。SSH fallback 只能直接发布零 Twist。

**Rationale**: 当前 rosbridge 直接发布 `/cmd_vel`，与 Nav2 共存会产生无法证明优先级的多发布者竞争。将来源分离后，可以测试人工接管、故障覆盖、来源超时和零速度切换。

**Alternatives rejected**:

- 让控制台和 Nav2 都发布 `/cmd_vel`：没有确定性仲裁，违反单一写入者。
- 依赖 Nav2 collision monitor：目标 Foxy 环境未核验该组件，且它不能替代驱动 watchdog。

## R2. Driver hardening and serial recovery

**Decision**: 在现有 `Mcnamu_driver_X3.py` 上增加纯逻辑限幅模块、有限值校验、300 ms watchdog、终止归零、串口健康检测、5 秒重建 `Rosmaster` 实例和 10 Hz `/chassis/connected`。驱动在 ROS graph 不显示唯一预期仲裁器时独立拒绝非零命令。

**Rationale**: 目标驱动已经适配 Rosmaster 串口协议；替换驱动会扩大硬件风险。当前 `set_car_motion()` 会吞掉部分串口异常，所以健康判断还必须观察底层 serial `is_open`、遥测读取异常和最近成功 I/O。

**Alternatives rejected**:

- 只在仲裁器限幅：无法防止仲裁器错误、非有限值或进程失联到达硬件。
- 高频无限重连：可能造成串口争用和 CPU/日志风暴；固定 5 秒退避更可诊断。

## R3. Odometry ownership

**Decision**: 将车端已安装的 C++ `icar_base_node` 纳入仓库，拆出可测试积分器，修复首帧时间基准、异常 `dt`、横移速度覆盖和协方差；发布 `/odom_raw`，不发布 odom TF。`robot_localization` 唯一发布 `/odom` 与 `odom → base_footprint`。

**Rationale**: 现节点第一帧可能用零时刻形成超大 `dt`，并在设置 `linear.y` 后立即覆盖为零；默认协方差过度乐观。保留 `/odom_raw → EKF → /odom` 链能融合 IMU 且保持唯一 TF 所有者。

**Alternatives rejected**:

- 让 base node 与 EKF 同时发布 TF：重复所有者会造成跳变。
- 直接把 `/vel_raw` 当 Nav2 odometry：缺少 pose、协方差和 frame 契约。

## R4. Canonical TF and lidar frame

**Decision**: 固定树为 `map → odom → base_footprint → base_link → laser_link/camera_link`。SLLIDAR 启动显式设置 `frame_id:=laser_link`，不增加 `laser → laser_link` 静态变换。

**Rationale**: 当前 `/scan` 使用 `laser`，URDF 使用 `laser_link`，属于命名错误而非额外物理坐标。用静态 TF 掩盖会制造两套传感器身份并降低配置可审阅性。

**Alternatives rejected**:

- 发布额外 `laser → laser_link`：掩盖启动参数问题并可能造成未来重复 TF。
- 统一改 URDF 为 `laser`：会破坏已有 description 与 Nav2 传感器配置约定。

## R5. Cartographer mode

**Decision**: 2D Cartographer 使用一个 LaserScan 和外部里程计：`tracking_frame=base_link`、`published_frame=odom`、`provide_odom_frame=false`、`use_odometry=true`。Cartographer 只在 mapping launch 中发布 `map → odom`。

**Rationale**: EKF 已拥有 odom frame；Cartographer 只需估计 map 对 odom 的校正。该配置避免 `odom → base` 的第二所有者。

**Alternatives rejected**:

- `provide_odom_frame=true`：与 EKF 所有权冲突。
- 同时启动 AMCL：两个 `map → odom` 发布者不可接受。
- 默认切换 GMapping：不满足用户指定主线；只可作为明确降级记录。

## R6. Nav2 Foxy contract

**Decision**: 使用 Foxy AMCL `robot_model_type: differential`、NavFn、DWB；controller 输出重映射到 `/cmd_vel_nav`，`min_vel_y=max_vel_y=0`。巡航直接顺序调用 `nav2_msgs/action/NavigateToPose`。

**Rationale**: 目标车已安装这些包和插件。车端接口核验显示 `NavigateToPose.Result` 只有 `std_msgs/Empty result`，所以成功/失败必须读取 action goal status，结合超时、取消和本地尝试记录。

**Alternatives rejected**:

- 读取较新 Nav2 的 error code/result 字段：Foxy 中不存在，会导致运行时失败。
- 直接使用 Waypoint Follower 完成全部业务：难以精确实现用户要求的停留、一次重试、skip 告警、人工接管取消和返航状态。
- 使用 TEB：不在目标范围，且目标环境未核验。

## R7. Patrol and route representation

**Decision**: 路线使用版本化 YAML，严格字段为 `frame_id`、`home`、`waypoints`、`default_dwell_sec`、`max_retries`、`failure_policy`、`loop`；启动前做有限数、角度和唯一名称校验。仓库只提供 `configured: false` 且坐标为 null 的不可运动模板；只有最终地图实测写入有限坐标并切换为 true 后才满足执行 schema。

**Rationale**: 路线与最终地图强绑定，在地图完成前编造坐标会形成危险的可执行默认值。纯数据模型便于离线测试和现场审阅。

**Alternatives rejected**:

- 在代码中硬编码坐标：不可审阅、不可现场替换。
- 提供看似可用的零坐标：可能误触发原地旋转或错误返航。

## R8. Safety state and reset semantics

**Decision**: 安全管理器以 10 Hz 产生权威许可与锁存故障，仲裁器通常只有在 `READY` 心跳不超过 0.30 秒时才输出非零速度。急停、底盘断连、雷达/odom/TF 陈旧、运行期所有权冲突和返航失败均锁存；故障恢复后仍需 `/safety/reset` 显式复位。唯一例外是 `LOW_BATTERY_RETURN`，且只在 10 Hz 活动巡航心跳不超过 0.30 秒并证明 `RETURN_HOME/NAVIGATING` 时放行该导航流。

**Rationale**: 单纯健康消息恢复不能证明场地仍安全或任务应该继续。显式复位提供清晰的人机边界。

**Alternatives rejected**:

- 自动解除故障并恢复导航：可能在操作者处理故障时突然运动。
- 让各节点自行决定是否允许运动：状态分散、无法形成单一证据。

## R9. Low-battery behavior

**Decision**: 默认 `enable_real_low_battery=false`；模拟服务进入与真实低电相同的返航路径。安全状态触发巡航管理器取消原任务并报告 `RETURN_HOME`，仲裁器使用 0.50 秒新鲜状态作为 fail-closed 授权，成功/失败原因再驱动安全终态。真实观察使用 10 点均值、10.8 V 触发、持续 5 秒、11.1 V 恢复迟滞。

**Rationale**: 车端当前约 11.3 V，但电池化学体系与安全规格尚未确认。模拟触发可完整验证任务取消、返航、失败锁止而不要求危险放电。

**Alternatives rejected**:

- 立即按单点电压触发：噪声会导致抖动，且阈值尚未获得电池规格依据。
- 完全不实现真实观察：失去未来启用前的数据和测试接口。

## R10. Public alarm compatibility

**Decision**: 新建 `car_interfaces/Alarm.msg` 发布 `/alarm`；同时将关键事件序列化到现有控制台可消费的 `/alarm_events` `std_msgs/String`。

**Rationale**: 强类型消息便于车端诊断和测试，兼容流避免重构已有控制台遥测。安全动作不依赖任一 UI 消费者在线。

**Alternatives rejected**:

- 只发自由文本：无法稳定过滤严重度、代码与 active/cleared 状态。
- 立即重写控制台协议：超出四天范围且增加对用户脏工作树的干扰。

## R11. Testing and evidence

**Decision**: 纯策略与解析逻辑在 Windows/CI 测试；ROS 导入、消息生成、launch 和 `colcon` 在 Foxy 容器测试；非运动 topic/TF/参数检查可直接连接 `192.168.43.137`；只有非零 Twist/action 需要用户批准。

**Rationale**: 抽取目录不包含完整车端依赖图，本机伪造 Foxy 环境会降低可信度。分层验证能在不移动硬件的情况下尽早发现大多数错误。

**Alternatives rejected**:

- 只做静态检查：无法证明 Foxy 插件和生成消息可用。
- 未经批准直接运行导航：违反硬件安全边界。

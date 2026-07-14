# Safety & Navigation Requirements Checklist: ROS2 核心与导航四天闭环

**Purpose**: 面向评审者检查安全与导航需求本身的完整性、明确性、一致性、可测量性和边界覆盖；不用于声明实现已经通过测试。
**Created**: 2026-07-13
**Feature**: [spec.md](../spec.md)
**Design**: [plan.md](../plan.md) · [ROS contracts](../contracts/ros-interfaces.md)

## Scope and Acceptance Quality

- [x] CHK001 是否明确把完整实车闭环而非仿真/静态检查定义为最终范围？[Spec §Clarifications, FR-001]
- [x] CHK002 五个用户故事是否按安全底座、建图、单点导航、三点巡航、故障返航排序且各自可独立验收？[Spec §User Scenarios]
- [x] CHK003 四个日门禁是否各自包含可观察证据，并明确前一门禁失败会阻止后续阶段？[Plan §Daily Gates]
- [x] CHK004 是否明确区分自动化/非运动、零速度和需用户批准的物理运动检查？[Spec FR-031..032; Quickstart §0, §7]
- [x] CHK005 是否为速率、延迟、地图误差、导航误差、重试次数和演示轮次给出数值标准？[Spec SC-002..009]
- [x] CHK006 是否明确本轮排除 TEB、自动充电、视觉融合、多楼层、GPS、发行版迁移和前端重构？[Spec §Assumptions]

## Motion Boundary and Chassis Safety

- [x] CHK007 是否枚举人工、导航、巡航/返航等全部运动请求来源，并为最终命令指定唯一常规所有者？[Spec §Safety Constraints; Contracts §1]
- [x] CHK008 是否明确急停/故障、人工、普通导航之间的优先级，以及低电只放行新鲜 `RETURN_HOME` 状态的例外？[Spec FR-004; Data Model §2]
- [x] CHK009 是否规定来源切换先归零、人工接管取消自主任务且不自动恢复？[Spec FR-005, FR-021]
- [x] CHK010 是否同时规定仲裁软限制、驱动独立硬限制和非有限数拒绝？[Spec FR-006; Contracts §7]
- [x] CHK011 是否明确 300 ms watchdog、安全/返航心跳新鲜度、0.40 秒命令超时停车门槛以及 0.50 秒故障停车门槛的关系？[Spec US1, FR-004, SC-003, SC-007; Contracts §7]
- [x] CHK012 是否覆盖正常终止、SIGINT/SIGTERM、串口异常、启动时串口缺失和重连后的行为？[Spec FR-007; Edge Cases]
- [x] CHK013 是否明确 SSH 灾难恢复只允许直接发送零速度而不能成为第二个常规运动来源？[Spec §Safety Constraints; Contracts §1]
- [x] CHK014 是否规定第一次和后续实车运动的分级限速，以及每项测试后的显式零 Twist？[Spec FR-032]

## Safety State, Failure, and Recovery

- [x] CHK015 是否定义启动宽限、健康允许、急停、底盘、传感器、里程计/TF、低电返航和返航失败状态？[Data Model §4]
- [x] CHK016 是否明确哪些故障必须锁存，以及 topic 恢复不能自动重新允许运动？[Spec FR-022; Data Model §4]
- [x] CHK017 安全复位的健康、零输出和无活动 action 前提是否明确且可判断？[Contracts §4]
- [x] CHK018 急停、串口、雷达、里程计/TF、命令超时、导航失败和低电是否都有结构化告警要求？[Spec FR-023; Contracts §3]
- [x] CHK019 告警是否定义稳定严重度、代码、来源、状态、消息、active/cleared 语义和去重身份？[Spec §Public Interfaces; Data Model §5]
- [x] CHK020 故障恢复是否要求记录触发、预期、观察、停车延迟和恢复结果，而非只记录“通过”？[Spec FR-029; Data Model §9]
- [x] CHK021 告警消费者/控制台离线时的底层安全独立性是否明确？[Spec Edge Cases, FR-024]

## Topic, TF, and Sensor Ownership

- [x] CHK022 是否定义完整 `map → odom → base_footprint → base_link → sensor` 链和每段唯一所有者？[Spec FR-010..012; Contracts §6]
- [x] CHK023 是否明确 EKF 是 `/odom` 和 `odom → base_footprint` 的唯一所有者，base node 不发布该 TF，且运行期 owner 冲突会锁止？[Spec FR-010..011; Contracts §6, §8]
- [x] CHK024 是否明确 Cartographer 与 AMCL 对 `map → odom` 的分模式唯一所有权，并禁止同时启动？[Spec FR-012; Contracts §6, §8]
- [x] CHK025 是否规定激光 frame 必须直接更正为 `laser_link`，且禁止用额外静态 TF 掩盖错误？[Spec FR-009; Safety Constraints]
- [x] CHK026 激光、里程计和 TF 的最低频率/新鲜度与启动宽限是否都有可测量定义？[Spec SC-002; Data Model §3; Contracts §7]
- [x] CHK027 是否覆盖 frame 不一致、TF 缺失、TF 重复发布和时间戳异常等边界？[Spec Edge Cases]

## Mapping and Navigation Quality

- [x] CHK028 Cartographer 使用外部 odom、单 LaserScan 且不提供 odom frame 的要求是否无歧义？[Research R5; Plan Phase 2]
- [x] CHK029 地图三种产物、两次重载、五地标误差、断廊和双墙质量门槛是否完整？[Spec FR-013..014, SC-004]
- [x] CHK030 Nav2 的差速约束、零横移、初始速度和目标/验收容差是否分别定义且不冲突？[Spec FR-015..017]
- [x] CHK031 Foxy `NavigateToPose` 空结果以及以 action status/超时/本地记录判定结果的要求是否明确？[Spec FR-016; Contracts §5]
- [x] CHK032 导航取消、拒绝、终止、超时、不可达和通信丢失是否都有结果语义？[Spec US3; Edge Cases]

## Patrol and Low-Battery Requirements

- [x] CHK033 路线必需字段、有限值/唯一名称校验、三点数量和地图实测来源是否明确？[Spec FR-018; Route schema]
- [x] CHK034 巡航状态、3 秒停留、一次重试、skip、非循环和两轮验收是否可测量？[Spec FR-019..020, SC-006]
- [x] CHK035 取消、人工接管、安全故障和低电是否都立即终止当前 goal，且低电只通过新鲜 `RETURN_HOME/NAVIGATING` 握手放行返航？[Spec FR-004, FR-021; Data Model §2, §7]
- [x] CHK036 模拟低电、真实低电默认关闭、10 点均值、10.8/11.1 V 迟滞和 5 秒持续条件是否完整？[Spec FR-025..026]
- [x] CHK037 Home 不可达时的原地锁止、零速度、高严重度告警和不恢复原任务是否明确？[Spec FR-027; US5]
- [x] CHK038 是否避免提供可误启动的伪造坐标，并要求路线 `configured=true` 才可执行？[Research R7; Data Model §6]

## Compatibility, Evidence, and Change Safety

- [x] CHK039 是否锁定目标 Foxy 已安装消息/action/插件，避免依赖较新发行版字段？[Spec SC-010; Research R6]
- [x] CHK040 本地逻辑测试、目标 Foxy build/test、非运动检查和实车证据是否形成分层验证要求？[Plan §Technical Context; Quickstart]
- [x] CHK041 控制台适配范围是否限于人工 topic、急停/复位、启动编排和测试？[Spec FR-028; Contracts §9]
- [x] CHK042 是否明确保护 `local-config.json`、凭据、host key、原始 rosbag、大日志和已有脏工作树？[Spec FR-029..030]
- [x] CHK043 当前车端地址是否只作为可变部署上下文而不是源代码凭据？[Spec Clarifications 2026-07-13; Assumptions]
- [x] CHK044 是否为 buildable 的每类需求提供了明确设计落点，以便 tasks 做到 100% 覆盖？[Plan §Project Structure, §Design Phases]

## Review Outcome

- Requirement-quality review: **44/44 complete**.
- Open clarification markers: **0**.
- Critical/high requirement-quality findings: **0**.
- Completion of this checklist authorizes task generation only; it does not claim code, build, vehicle motion, mapping, navigation, or final acceptance has passed.

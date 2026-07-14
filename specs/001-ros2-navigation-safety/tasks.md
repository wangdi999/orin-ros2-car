# Tasks: ROS2 核心与导航四天闭环

**Input**: [spec.md](./spec.md), [plan.md](./plan.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md)
**Test policy**: 运动、安全、TF、导航和故障处理任务必须包含自动化或可复核测试。只有已执行并有证据的任务可标为 `[X]`。
**Physical marker**: `[MOTION-GATE]` 表示会导致或可能导致小车移动，执行前必须得到用户明确批准；每项结束发送零 Twist。

**2026-07-13 execution note**: 用户已恢复本地和车端非运动测试；当前目标地址由 `local-config.json` 或运行参数决定（现为 `192.168.43.137`）。`[MOTION-GATE]` 仍须逐项取得明确批准；只有已执行并留有证据的任务才标记 `[X]`。

## Phase 1: Setup and Baseline Preservation

**Purpose**: 建立可审阅目录、忽略边界和修改前证据，不触碰用户无关改动。

- [X] T001 记录初始 `git status`、控制台 36/36 测试结果与车端只读运行基线到 `specs/001-ros2-navigation-safety/validation/baseline.md`
- [X] T002 [P] 在根 `.gitignore` 中忽略 `artifacts/navigation/raw/`、rosbag 和临时部署产物，同时保留可提交验收摘要与地图
- [X] T003 [P] 为 `car_interfaces`、`icar_base_node`、`icar_navigation` 创建 ROS 包骨架与资源安装规则，路径为 `ros2_car_remote_ws/src/{car_interfaces,icar_base_node,icar_navigation}/`
- [X] T004 [P] 创建部署与证据脚本骨架 `scripts/deploy_ros2_navigation.ps1` 和 `scripts/collect_navigation_evidence.ps1`，禁止嵌入密码或 host key
- [X] T005 复核 `AGENTS.md` 仅在 `SPECKIT` 托管区新增 plan 链接，并将脏工作树保护结果写入 `specs/001-ros2-navigation-safety/validation/baseline.md`

---

## Phase 2: Foundational Contracts and Test Harness

**Purpose**: 所有用户故事共享的消息、纯逻辑、配置校验和安全门禁。

**CRITICAL**: 本阶段通过前不接入任何运动链路。

- [X] T006 [P] 在 `ros2_car_remote_ws/src/car_interfaces/msg/Alarm.msg` 实现 Alarm 公共契约，并配置 `CMakeLists.txt`/`package.xml` 生成 Foxy 消息
- [X] T007 [P] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/motion_policy.py` 建立有限数、限幅、来源新鲜度和零切换纯逻辑
- [X] T008 [P] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/safety_policy.py` 建立健康快照、锁存、复位前提和低电迟滞纯逻辑
- [X] T009 [P] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/route_loader.py` 实现严格路线解析、不可执行占位保护和唯一航点校验
- [X] T010 [P] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/patrol_policy.py` 实现 Foxy action 状态到重试/skip/cancel/return-home 状态转换
- [X] T011 [P] 为 T007-T010 分别添加 pytest：`ros2_car_remote_ws/src/icar_navigation/test/test_{motion_policy,safety_policy,route_loader,patrol_policy}.py`
- [X] T012 [P] 在 `ros2_car_remote_ws/src/icar_navigation/test/test_config_contracts.py` 静态验证 YAML/Lua/launch、唯一 topic/TF 所有者和路线契约
- [X] T013 配置 `ros2_car_remote_ws/src/icar_navigation/{package.xml,setup.py,setup.cfg,resource/icar_navigation}` 安装节点、launch、config、maps 和 scripts

**Checkpoint**: 纯策略测试可在没有 ROS/Foxy 的本机运行，消息和 ROS 包结构可供 D1 使用。

---

## Phase 3: User Story 1 - 安全底盘与人工接管 / D1 (Priority: P1) 🎯 MVP

**Goal**: 建立唯一、限幅、超时、可急停、可恢复且有 odom/TF 的最终运动边界。

**Independent Test**: 无地图/Nav2 时完成单元测试、Foxy 构建、只读/零速度检查；经批准后再做最低速短脉冲与故障停车。

### Tests for User Story 1

- [X] T014 [P] [US1] 在 `ros2_car_remote_ws/src/icar_bringup/test/test_driver_safety.py` 覆盖 NaN/Inf、三轴硬限幅、300 ms timeout、重复零命令和重连退避
- [X] T015 [P] [US1] 在 `ros2_car_remote_ws/src/icar_base_node/test/test_odometry_integrator.cpp` 覆盖首帧、正常 `dt`、异常/倒退 `dt`、X3 横移和非有限反馈
- [X] T016 [P] [US1] 扩展 `ros2_car_remote_ws/src/icar_navigation/test/test_motion_policy.py` 覆盖人工优先、安全心跳陈旧 fail closed、故障覆盖、来源切换零周期、人工接管取消标记、导航 `linear.y=0` 和只凭 0.30 秒内 `RETURN_HOME/NAVIGATING` 握手放行返航
- [X] T017 [P] [US1] 扩展 `ros2_car_remote_ws/src/icar_navigation/test/test_safety_policy.py` 覆盖启动宽限、急停/底盘/scan/odom-TF/所有权锁存、10 Hz 底盘心跳新鲜度、健康恢复不自动复位和 reset 拒绝原因
- [X] T018 [P] [US1] 在 `smart-car-console/server/rosbridge.test.mjs`、`control.test.mjs` 和 `serviceManager.test.mjs` 增加人工 topic、急停/复位和互斥启动回归测试

### Implementation for User Story 1

- [X] T019 [US1] 在 `ros2_car_remote_ws/src/icar_bringup/icar_bringup/driver_safety.py` 实现可单测的驱动限幅、watchdog 和退避策略
- [X] T020 [US1] 加固 `ros2_car_remote_ws/src/icar_bringup/icar_bringup/Mcnamu_driver_X3.py`：有限值、0.35/0.35/0.80 硬限、300 ms watchdog、启动/终止归零、串口健康、5 秒重连、10 Hz `/chassis/connected` 和 `/cmd_vel` 发布者身份 fail-closed 检查
- [X] T021 [US1] 更新 `ros2_car_remote_ws/src/icar_bringup/{package.xml,setup.py,launch/icar_bringup_X3_launch.py}` 的依赖、参数和安全启动，强制 base node 不发布 odom TF
- [X] T022 [US1] 在 `ros2_car_remote_ws/src/icar_base_node/include/icar_base_node/odometry_integrator.hpp` 与 `src/odometry_integrator.cpp` 实现防首帧/异常 `dt` 的 X3 积分和协方差模型
- [X] T023 [US1] 在 `ros2_car_remote_ws/src/icar_base_node/src/base_node_X3.cpp` 订阅 `/vel_raw`、发布 `/odom_raw`，保留横移并默认禁止 TF
- [X] T024 [US1] 配置 `ros2_car_remote_ws/src/icar_base_node/{CMakeLists.txt,package.xml}` 的 Foxy 构建、安装和 gtest
- [X] T025 [P] [US1] 在 `ros2_car_remote_ws/src/icar_navigation/config/ekf.yaml` 配置 `/odom_raw` + `/imu/data` 融合并独占 `/odom` 与 `odom→base_footprint`
- [X] T026 [US1] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/cmd_vel_arbiter.py` 接入 `/cmd_vel_manual`、`/cmd_vel_nav`、10 Hz `/safety/state` 和活动期 10 Hz `/patrol/status`，对两类授权执行 0.30 秒 fail-closed，独占 `/cmd_vel` 并发布包括 `RETURN_HOME` 的 `/control/active_source`
- [X] T027 [US1] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/safety_manager.py` 接入急停、底盘、scan、odom、TF、ROS graph owner、patrol status 和 voltage 健康，提供 `/safety/state`、reset、模拟低电和 Alarm
- [X] T028 [P] [US1] 在 `ros2_car_remote_ws/src/icar_navigation/config/{arbiter.yaml,safety.yaml}` 写入软限、timeout、新鲜度、锁存和真实低电默认关闭参数
- [X] T029 [US1] 在 `ros2_car_remote_ws/src/icar_navigation/launch/safe_base.launch.py` 编排 description、SLLIDAR `laser_link`、驱动、base node、IMU filter、EKF、仲裁和安全节点
- [X] T030 [US1] 将 `smart-car-console/server/rosbridge.mjs` 的人工发布改为 `/cmd_vel_manual`，并实现 `/safety/estop`、`/safety/reset` 调用与零-only SSH fallback
- [X] T031 [US1] 最小更新 `smart-car-console/server/{index.mjs,serviceManager.mjs,state.mjs}` 和 `src/App.jsx`，展示活动来源/安全状态并提供急停与复位结果，不重构页面
- [X] T032 [US1] 执行本机 US1 测试、完整 `npm test` 与 `npm run build`，把结果写入 `specs/001-ros2-navigation-safety/validation/d1-software.md`
- [X] T033 [US1] 使用 `192.168.160.196` 在 Foxy staging overlay 构建/test 四个相关包，并记录 Alarm/NavigateToPose 接口到 `specs/001-ros2-navigation-safety/validation/d1-foxy.md`
- [X] T034 [US1] 在车端只启动 safe base，不发送非零命令，验证 `/scan ≥5 Hz`、`/odom ≥20 Hz`、laser frame、TF 完整唯一、单一 `/cmd_vel` 和零终态，记录到 `validation/d1-non-motion.md`
- [ ] T035 [US1] **[MOTION-GATE]** 经批准以 `0.05/0.20` 完成人工短脉冲、300 ms timeout、来源切换、急停、SIGTERM 和串口拔插停车/恢复，每项发零并记录停止延迟到 `validation/d1-motion.md`
- [ ] T036 [US1] 汇总 D1 门禁；只有 T032-T035 全部 PASS 才在 `validation/d1-gate.md` 标记 D1 通过

**Checkpoint**: D1 通过前，禁止执行任何 D2-D4 物理运动任务。

---

## Phase 4: User Story 2 - 生成并复用室内地图 / D2 (Priority: P2)

**Goal**: 用唯一 TF 所有权和外部 odom 建立可保存、可重载、可测量质量的 Cartographer 地图。

**Independent Test**: mapping 模式静态/零速度检查不依赖 Nav2；实车路线与地图质量仅在 D1 门禁通过后执行。

### Tests for User Story 2

- [X] T037 [P] [US2] 扩展 `ros2_car_remote_ws/src/icar_navigation/test/test_config_contracts.py`，断言 Cartographer frame/odom 参数、单 LaserScan 和 mapping/navigation 互斥
- [X] T038 [P] [US2] 在 `ros2_car_remote_ws/src/icar_navigation/test/test_map_artifacts.py` 覆盖同名 PGM/YAML/PBStream、YAML image 引用和两次 reload 证据结构

### Implementation for User Story 2

- [X] T039 [US2] 在 `ros2_car_remote_ws/src/icar_navigation/config/cartographer_2d.lua` 实现 Foxy 2D 单 LaserScan + 外部 odom 配置
- [X] T040 [US2] 在 `ros2_car_remote_ws/src/icar_navigation/launch/mapping.launch.py` 编排 safe base、Cartographer 与 occupancy grid，并拒绝定位模式冲突
- [X] T041 [P] [US2] 在 `ros2_car_remote_ws/src/icar_navigation/scripts/save_map.sh` 原子保存 `campus_map.pgm/.yaml/.pbstream` 并拒绝不完整产物
- [X] T042 [US2] 车端以 mapping 模式做非运动检查：Cartographer 存在、AMCL 缺席、一个 `map→odom`、地图 topic 可见，记录到 `validation/d2-non-motion.md`
- [ ] T043 [US2] **[MOTION-GATE]** D1 通过后在受控室内完成建图路线，每段结束发零，保存三类 `campus_map` 产物到 `ros2_car_remote_ws/src/icar_navigation/maps/`
- [ ] T044 [US2] 对 `campus_map` 连续重载两次并测量五个固定地标、断廊和双墙，将证据写入 `validation/d2-map-quality.md`
- [ ] T045 [US2] 汇总 D2 门禁；只有 T037-T044 全部 PASS 才在 `validation/d2-gate.md` 标记 D2 通过

**Checkpoint**: D2 通过前，不执行任何 Nav2 目标或巡航运动。

---

## Phase 5: User Story 3 - 单点自主导航 / D3A (Priority: P3)

**Goal**: 在已验收地图上完成可取消、按 Foxy action 状态判定的精确单点导航。

**Independent Test**: Nav2 启动、插件、remap 和 action 类型可非运动验证；目标运动必须等待 D2 门禁和用户批准。

### Tests for User Story 3

- [X] T046 [P] [US3] 扩展 `test_config_contracts.py`，验证 AMCL differential、NavFn、DWB、footprint、`linear.y=0`、0.10/0.40 与 0.15/0.15 配置
- [X] T047 [P] [US3] 在 `ros2_car_remote_ws/src/icar_navigation/test/test_patrol_policy.py` 覆盖 Foxy succeeded/aborted/canceled/rejected/timeout，不访问 post-Foxy result 字段

### Implementation for User Story 3

- [X] T048 [US3] 在 `ros2_car_remote_ws/src/icar_navigation/config/nav2_foxy.yaml` 配置 AMCL、Map Server、NavFn、DWB、costmaps、footprint、速度和 goal checker
- [X] T049 [US3] 在 `ros2_car_remote_ws/src/icar_navigation/launch/navigation.launch.py` 编排 safe base、Map Server、AMCL、Nav2 servers，并将 controller 输出 remap 到 `/cmd_vel_nav`
- [X] T050 [P] [US3] 在 `ros2_car_remote_ws/src/icar_navigation/scripts/verify_navigation.sh` 实现只读插件、action、topic owner 和 TF 门禁检查
- [X] T051 [US3] 使用 `192.168.160.196` 车端启动 navigation 但不设置 goal，验证 AMCL/Nav2 存在、Cartographer 缺席、唯一 `map→odom` 和速度 remap，记录到 `validation/d3-non-motion.md`
- [ ] T052 [US3] **[MOTION-GATE]** D2 通过后以批准限速设置初始位姿并执行一个可达目标，测量位置/朝向误差与取消停车，记录到 `validation/d3-single-goal.md`

---

## Phase 6: User Story 4 - 三点巡航 / D3B (Priority: P4)

**Goal**: 用最终地图路线完成两轮三点巡航，并验证一次重试、skip 告警和取消。

**Independent Test**: 路线解析和状态机可用纯逻辑验证；实车只在单点导航通过后执行。

### Tests for User Story 4

- [X] T053 [P] [US4] 扩展 `test_route_loader.py` 覆盖空/缺字段、非有限坐标、重复名称、null 坐标未配置模板、`configured:true` 拒绝 null、Home、三点数量和默认值
- [X] T054 [P] [US4] 扩展 `test_patrol_policy.py` 覆盖 `IDLE→NAVIGATING→ARRIVED→WAITING→NEXT_GOAL`、一次重试、skip/abort、loop=false 和人工/故障取消

### Implementation for User Story 4

- [X] T055 [US4] 在 `ros2_car_remote_ws/src/icar_navigation/icar_navigation/patrol_manager.py` 实现 Foxy `NavigateToPose` 顺序 action client、3 秒停留、重试/skip、取消和 return-home
- [X] T056 [P] [US4] 在 `ros2_car_remote_ws/src/icar_navigation/config/patrol_route.yaml` 提供 `configured:false` 且坐标为 null 的安全模板，包含 Home、三个航点和固定策略字段
- [X] T057 [US4] 将 patrol 节点与三个 Trigger 服务加入 `navigation.launch.py`/`demo.launch.py`，路线未配置时 fail closed
- [X] T058 [US4] 在控制台 `server/rosbridge.mjs`/`state.mjs` 与 `src/App.jsx` 最小接入 `/patrol/status` 和 start/cancel/return-home 服务状态
- [ ] T059 [US4] **[MOTION-GATE]** 录入最终地图实测坐标并连续完成两轮三点巡航，记录每点到达/停留到 `validation/d3-patrol.md`
- [ ] T060 [US4] **[MOTION-GATE]** 设置一个不可达航点，验证只重试一次、skip 告警、后续继续与最终零速度，记录到 `validation/d3-unreachable.md`
- [ ] T061 [US4] 汇总 D3 门禁；只有 T046-T060 适用项全部 PASS 才在 `validation/d3-gate.md` 标记 D3 通过

---

## Phase 7: User Story 5 - 故障保护与低电返航 / D4 (Priority: P5)

**Goal**: 统一 Alarm、故障注入、模拟低电返航、失败锁止和一键 Demo。

**Independent Test**: 告警、锁存、迟滞和故障状态可先纯逻辑/零速度验证；返航和综合 Demo 运动需批准且依赖 D3。

### Tests for User Story 5

- [X] T062 [P] [US5] 扩展 `test_safety_policy.py` 覆盖 10 点均值、10.8 V 持续 5 秒、11.1 V 恢复、真实触发禁用和模拟触发
- [X] T063 [P] [US5] 在 `ros2_car_remote_ws/src/icar_navigation/test/test_alarm_contract.py` 覆盖 severity/code/source/state/message/active、去重和 `/alarm_events` JSON 兼容
- [X] T064 [P] [US5] 扩展 `test_patrol_policy.py` 覆盖低电取消原任务、Home 成功锁停、Home 失败 `RETURN_FAILED` 且不恢复原任务
- [X] T065 [P] [US5] 扩展控制台测试，覆盖 Alarm 兼容流、模拟低电/返航服务结果和复位失败不清 UI 状态

### Implementation for User Story 5

- [X] T066 [US5] 完成 `safety_manager.py` 的 Alarm 去重/清除、模拟与真实低电状态路径、从 `/patrol/status.reason` 接收返航结果和失败锁存
- [X] T067 [US5] 完成 `patrol_manager.py` 对 `LOW_BATTERY_RETURN` 的取消/返航协作、活动期 10 Hz `RETURN_HOME` 授权心跳、成功后保持停止和失败高严重度告警
- [X] T068 [US5] 在 `ros2_car_remote_ws/src/icar_navigation/launch/demo.launch.py` 组合已验收 navigation/route，保持 `enable_real_low_battery=false`
- [X] T069 [US5] 在 `scripts/collect_navigation_evidence.ps1` 实现脱敏 topic/TF/action/停止时间采集并输出 `AcceptanceEvidence` 结构
- [ ] T070 [US5] 使用 `192.168.43.137` 完成急停、命令超时、雷达、odom/TF、串口和 SIGTERM 的非运动/零速度故障检查，记录到 `validation/d4-non-motion-faults.md`（急停/超时/雷达/EKF/SIGTERM 已通过；物理串口拔插仍待 T035 运动门禁）
- [ ] T071 [US5] **[MOTION-GATE]** D3 通过后执行模拟低电返回 Home 和不可达 Home 锁止，记录到 `validation/d4-return-home.md`
- [ ] T072 [US5] **[MOTION-GATE]** 以批准限速连续完成两次综合 Demo，并记录到 `validation/d4-demo.md`
- [ ] T073 [US5] 汇总 D4 门禁；只有 T062-T072 全部 PASS 才在 `validation/d4-gate.md` 标记 D4 通过

---

## Phase 8: Polish and Cross-Cutting Verification

**Purpose**: 完成部署可重复性、文档、全套回归、接口覆盖和最终交接。

- [X] T074 [P] 完成 `scripts/deploy_ros2_navigation.ps1` 的 staging、选包构建、dry-run、失败不切换 overlay 和无凭据输出
- [X] T075 [P] 更新 `docs/AI_CAR_CONNECTION_AND_DEVELOPMENT.md`，记录新 topic/service、互斥模式、`192.168.160.196` 作为当前可变地址和运动批准流程
- [X] T076 [P] 更新 `smart-car-console/local-config.example.json` 只增加非敏感导航默认项；验证 `local-config.json` 仍被忽略且未修改
- [X] T077 运行全部 Python/C++/ROS/Node 测试与控制台 build，执行 `quickstart.md` 非运动部分，把版本、命令和结果写入 `validation/final-software.md`
- [X] T078 对照 FR-001..FR-032 检查 task/evidence 覆盖率 100%，并在 `validation/requirements-traceability.md` 记录每条需求状态
- [X] T079 重新运行 `speckit-analyze`；只有 0 CRITICAL、0 HIGH 且无未决 checklist 才允许声明实现阶段完成
- [X] T080 在 `specs/001-ros2-navigation-safety/validation/final-acceptance.md` 汇总 D1-D4；未执行的物理任务必须标为 BLOCKED/PENDING，不得写成 PASS

---

## Phase 9: Truthful Web Capability Visualization

**Purpose**: 让控制台只展示当前 X3 小车真实存在或已确认的软件能力，补齐地图、导航和视觉只读显示，并删除虚假遥测与模拟占位数据。

- [X] T081 记录本轮脏工作树、车端 X3/ORBBEC/ROS 包只读基线，并确认不改变 D1-D4 运动门禁
- [ ] T082 [P] 为能力注册表、ORBBEC 探测、X3 过滤、容器停止、缓存/脱敏和厂家运动能力阻塞添加 Node 单元测试
- [ ] T083 实现只读能力注册表、持久化脱敏缓存、`GET /api/capabilities` 和 WebSocket snapshot 状态
- [ ] T084 [P] 为 TF 组合、AMCL 优先级、Path/costmap 降采样、过期真实帧和无模拟数据添加遥测单元测试
- [ ] T085 扩展 rosbridge/topic registry，接入 TF、AMCL、Nav2 路径/代价地图/action 状态与巡航路线只读遥测
- [ ] T086 在 `patrol_manager` 发布 transient-local `/patrol/route` `nav_msgs/msg/Path`，并添加配置/空路线/QoS 测试
- [ ] T087 删除环境、附属电量、电流/功率、伪编码器和模拟雷达/点云显示，保留真实数据并标记过期时间
- [ ] T088 实现“能力中心”“地图与导航”“视觉”页面及只读图层、状态、阻塞原因和开发者详情
- [ ] T089 运行完整 Node/Python 回归、控制台生产构建与桌面布局检查，不执行任何运动/导航/巡航命令
- [ ] T090 更新开发文档和验收摘要，记录公共接口、已删除字段、未运行能力和只读验证结果

---

## Phase 10: Full Web Mapping and Navigation Workbench

**Purpose**: 在保持 `/cmd_vel` 单一安全边界的前提下，把主线建图、地图管理、定位、单点导航和三点巡航完整接入本地网页。

- [X] T091 [P] 为网页导航协议、地图/路线校验、模式切换和首次运动提示添加 Node/Python 单元测试
- [X] T092 在 `car_interfaces` 增加 `NavigatePose.srv` 并更新 Foxy 接口依赖
- [X] T093 扩展巡航管理器，统一拥有单点目标、巡航和返航 action，并发布 `/navigation/status`
- [X] T094 为路线热重载和统一导航状态补充 ROS 服务、topic、launch 与注册表接入
- [X] T095 实现控制台地图/路线管理器、托管目录、完整性校验、逻辑归档、恢复、预览和下载
- [X] T096 实现串行导航工作流、零优先模式切换、初始位姿、单点目标和首次运动提示后端门禁
- [X] T097 暴露计划中的本地 HTTP API，并保持输入白名单、回环访问和统一错误结构
- [X] T098 实现“建图、地图、定位、单点导航、路线巡航”分步工作台和交互地图工具
- [X] T099 扩展开发手册和接口契约，记录网页工作流、存储路径、安全门禁与未覆盖的厂家能力
- [X] T100 运行完整 Node/Python 回归和控制台生产构建，修复所有非物理失败
- [ ] T101 在 Foxy 环境执行四包 build/test 与只读接口检查，不发送目标或非零 Twist
- [X] T102 汇总软件/非运动验收；实车建图、目标、巡航和返航继续保持运动门禁未通过

---

## Dependencies and Execution Order

### Phase Dependencies

- **Phase 1**: 无依赖，先保护工作树。
- **Phase 2**: 依赖 Phase 1；阻塞所有 ROS 运行接入。
- **US1 / D1 code**: 依赖 Phase 2；D1 物理门禁 T035 阻塞后续物理运动，但不阻止在本地完成后续代码和静态测试。
- **US2 / D2 code**: 依赖 US1 软件链；T043 物理建图必须在 T036 PASS 后。
- **US3 / D3A code**: 依赖地图接口设计；T052 物理目标必须在 T045 PASS 后。
- **US4 / D3B code**: 依赖 US3 action contract；T059/T060 必须在 T052 PASS 后。
- **US5 / D4 code**: 依赖 US1 安全和 US4 return-home；T071/T072 必须在 T061 PASS 后。
- **Phase 8**: 软件回归可在代码完成后执行；最终实车验收依赖所有日门禁。

### User Story Dependency Graph

```text
Setup -> Foundation -> US1 Safe Base
                         |
                         +-> US2 Mapping -> US3 Single Goal -> US4 Patrol -> US5 Fault/Return
                         |
                         `-> US5 pure safety/alarm tests
```

### Parallel Opportunities

- T006-T012 可并行：消息、四个纯逻辑模块与静态测试修改不同文件。
- T014-T018 可并行先写测试；T022-T025 可与驱动 T019-T021 并行。
- T037-T041 可在 US1 软件接口稳定后并行完成配置、测试和保存脚本。
- T046-T050 与 T053-T056 可按 action/route 契约并行，但巡航 ROS 接入 T055 依赖 T047/T054。
- T062-T065 可并行；T066/T067 分别依赖安全与巡航测试。
- 所有 `[MOTION-GATE]` 任务严格串行，并在每项后验证零 Twist。

## Requirement Traceability

| Requirements | Primary tasks |
|---|---|
| FR-001, FR-029 | T001, T032-T036, T042-T045, T051-T061, T069-T080 |
| FR-002, FR-006..009 | T014-T025, T029, T033-T035 |
| FR-003..005 | T007, T016, T026, T030-T035 |
| FR-010..012 | T012, T025, T029, T034, T037, T040, T042, T049, T051 |
| FR-013..014 | T037-T045 |
| FR-015..017 | T046-T052 |
| FR-018..021 | T009-T011, T047, T053-T061 |
| FR-022..027 | T008, T017, T027, T062-T073 |
| FR-028 | T018, T030-T031, T058, T065 |
| FR-030 | T001-T005, T069, T074-T076 |
| FR-031..032 | T034-T035, T042-T045, T051-T052, T059-T060, T070-T072 |

Buildable requirement task coverage: **32/32 (100%)**.

## Implementation Strategy

1. 先交付 US1 软件 MVP 和所有非运动检查。
2. 顺序完成 US2-US5 代码、测试与 Foxy 非运动验证，不跨越任何物理门禁执行运动。
3. 向用户汇报所有自动化/非运动结果并请求第一次运动批准。
4. 获批后严格按 D1→D2→D3→D4 执行；任何 gate FAIL 立即停止后续运动。
5. 最终只把有证据的任务标为 `[X]`，其余保持开放并说明阻塞条件。

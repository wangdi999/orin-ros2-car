# AI 小车连接与后续开发手册

本手册面向后续接手的 AI 或开发者，目标是快速理解当前遥控项目的边界、连接方式、运行命令和可改动位置。

## 1. 项目边界

本迁移包提取的是“小车遥控相关项目”，不是整车系统镜像。

包含内容：

- `smart-car-console/`: Windows 侧网页控制台。前端采集键盘、摇杆和按钮操作，后端通过 SSH 管理车端服务，并通过 rosbridge 发布 `/cmd_vel`。
- `ros2_car_remote_ws/src/icar_ctrl/`: 原车 ROS2 遥控包，包含键盘控制和手柄控制节点。
- `ros2_car_remote_ws/src/icar_bringup/`: 原车底盘启动和驱动相关源码，重点参考 `icar_bringup/Mcnamu_driver_X3.py`。
- `scripts/connect_car_vnc.ps1`: Windows 侧 VNC 连接脚本。
- `wifi/ohcar_wifi_profile.xml`: 手册中使用的 `ohcar` Wi-Fi 配置。

未包含内容：

- `node_modules/`、`dist/`、运行日志、`local-config.json`。
- 导航、SLAM、完整雷达/相机 SDK、完整 `icar_ws` 和 `software/library_ws`。
- 车端 Docker 镜像 `icar/ros-foxy:1.0.2` 及其已安装依赖。

## 2. 架构速览

控制链路：

```text
浏览器 UI
  -> POST /api/drive
  -> smart-car-console/server/control.mjs 生成 Twist
  -> smart-car-console/server/rosbridge.mjs
  -> ws://<car-ip>:9090
  -> ROS2 topic /cmd_vel
  -> 车端底盘驱动 Mcnamu_driver_X3
  -> 底盘串口设备
```

服务启动链路：

```text
浏览器点击启动服务
  -> POST /api/services/start
  -> smart-car-console/server/serviceManager.mjs
  -> plink SSH 到 jetson@<car-ip>
  -> 启动或复用 Docker 容器 smartcar_icar_console
  -> 启动底盘驱动、雷达、rosbridge、视频流
```

关键 topic：

- `/cmd_vel`: `geometry_msgs/msg/Twist`，遥控运动命令。
- `/joy`: `sensor_msgs/msg/Joy`，手柄输入。
- `/JoyState`: `std_msgs/msg/Bool`，手柄控制启用状态。
- `/scan`: `sensor_msgs/msg/LaserScan`，雷达遥测。
- `/imu/data_raw`: `sensor_msgs/msg/Imu`，IMU 遥测。
- `/voltage`: `std_msgs/msg/Float32`，电压遥测。
- `/vel_raw`: `geometry_msgs/msg/Twist`，底盘速度反馈。
- `/joint_states`: `sensor_msgs/msg/JointState`，编码器或关节状态。

`/cmd_vel` 约定：

- `linear.x`: 前进或后退，单位 m/s。
- `linear.y`: 横移，X3 麦克纳姆底盘可用，单位 m/s。
- `angular.z`: 原地转向，单位 rad/s。
- 全 0 Twist 是停车命令。

## 3. 默认连接参数

这些参数来自当前项目和实验手册。若 IP 变化，以小车屏幕或车端终端显示的 `MY_IP` 为准。

| 项目 | 默认值 |
| --- | --- |
| Wi-Fi 名称 | `ohcar` |
| Wi-Fi 密码 | 本地私有配置，不提交仓库 |
| 当前小车 IP | `192.168.43.137` |
| SSH 用户 | `jetson` |
| SSH 密码 | 本地私有配置，不提交仓库 |
| VNC 密码 | 本地私有配置，不提交仓库 |
| SSH 端口 | `22` |
| VNC 端口 | `5900` |
| rosbridge 端口 | `9090` |
| 视频流端口 | `6500` |
| Windows plink 默认路径 | `D:\putty\plink.exe` |

注意：这些是实验设备默认参数。公开代码仓库中只保留占位说明，真实密码应写入本地私有配置或在 UI 中输入。

## 4. Windows 侧准备

需要：

- Node.js 和 npm。
- PuTTY `plink.exe`，默认配置路径为 `D:\putty\plink.exe`。如果不在这里，修改 `smart-car-console/local-config.json` 或在网页设置里更新。
- TigerVNC Viewer，默认路径为 `C:\Program Files\TigerVNC\vncviewer.exe`。

如需导入 Wi-Fi 配置：

```powershell
cd D:\code\project\smart-car-remote-control-20260707
netsh wlan add profile filename="wifi\ohcar_wifi_profile.xml"
netsh wlan connect name=ohcar
```

## 5. 连接小车

1. 给小车上电，等待 Ubuntu 桌面和终端启动完成。
2. 确认小车连接到 `ohcar`，或电脑和小车处于同一网段。
3. 在小车屏幕或 VNC 里的终端确认当前 IP。当前配置为 `192.168.43.137`。
4. 在 Windows PowerShell 检查连通性：

```powershell
ping 192.168.43.137
Test-NetConnection 192.168.43.137 -Port 22
Test-NetConnection 192.168.43.137 -Port 5900
```

5. 使用 VNC 连接小车桌面：

```powershell
cd D:\code\project\smart-car-remote-control-20260707
.\scripts\connect_car_vnc.ps1 -CarIp 192.168.43.137
```

6. VNC 密码使用本地私有设备密码。

## 6. 运行网页遥控控制台

首次运行：

```powershell
cd D:\code\project\smart-car-remote-control-20260707\smart-car-console
npm install
npm run dev
```

打开：

```text
http://127.0.0.1:5173
```

本地 API 默认监听：

```text
http://127.0.0.1:8787
```

配置文件：

- 示例配置：`smart-car-console/local-config.example.json`
- 本地私有配置：`smart-car-console/local-config.json`
- 如果 `local-config.json` 不存在，后端会使用示例配置或代码默认值。

建议首次运行时在 UI 设置里确认：

- 小车 IP。
- SSH 用户和密码。
- SSH host key。
- `plink.exe` 路径。
- 最大线速度、最大角速度和死区。

## 7. 控制台 API 速查

状态：

```http
GET /api/status
```

启动车端服务：

```http
POST /api/services/start
```

停止本控制台启动的服务：

```http
POST /api/services/stop
```

急停：

```http
POST /api/emergency-stop
```

发送遥控输入：

```http
POST /api/drive
Content-Type: application/json

{
  "forward": 0.2,
  "strafe": 0,
  "turn": 0,
  "linearLimit": 0.1,
  "angularLimit": 0.3
}
```

遥测 WebSocket：

```text
ws://127.0.0.1:8787/api/telemetry
```

视频代理：

```http
GET /api/video
```

## 8. 关键代码位置

网页和交互：

- `smart-car-console/src/App.jsx`: 主界面、状态面板、服务按钮、摇杆和设置弹窗。
- `smart-car-console/src/keyboardDrive.js`: W/A/S/D、方向键、Q/E 到遥控向量的映射。
- `smart-car-console/src/styles.css`: 控制台样式。

后端 API：

- `smart-car-console/server/index.mjs`: HTTP API、静态文件服务、遥测 WebSocket、急停入口。
- `smart-car-console/server/control.mjs`: 归一化输入、死区、限速、Twist 生成。
- `smart-car-console/server/rosbridge.mjs`: 连接 `ws://<car-ip>:9090`，订阅遥测 topic，发布 `/cmd_vel`。
- `smart-car-console/server/serviceManager.mjs`: 通过 SSH 启动 Docker、底盘驱动、雷达、rosbridge 和视频服务。
- `smart-car-console/server/ssh.mjs`: plink 调用封装。
- `smart-car-console/server/state.mjs`: 运行状态、遥测状态、canDrive 阻塞条件。
- `smart-car-console/server/config.mjs`: 本地配置读取、保存和对外隐藏密码。

ROS2 车端遥控：

- `ros2_car_remote_ws/src/icar_ctrl/icar_ctrl/icar_keyboard.py`: 终端键盘遥控节点，发布 `cmd_vel`。
- `ros2_car_remote_ws/src/icar_ctrl/icar_ctrl/icar_joy_X3.py`: X3 手柄遥控节点。
- `ros2_car_remote_ws/src/icar_ctrl/icar_ctrl/icar_joy_R2.py`: R2 手柄遥控节点。
- `ros2_car_remote_ws/src/icar_bringup/icar_bringup/Mcnamu_driver_X3.py`: X3 底盘驱动参考，订阅 `cmd_vel`。
- `ros2_car_remote_ws/src/icar_bringup/launch/icar_bringup_X3_launch.py`: X3 bringup launch 参考。它依赖车端已有的 `icar_description`、`icar_base_node`、`robot_localization`、`imu_filter_madgwick` 等包。

## 9. 安全测试流程

物理小车测试前：

1. 确认周围空旷，或将小车架起让轮子悬空。
2. 先只测试急停和零速度。
3. 初始速度使用低值：`linearLimit <= 0.1`，`angularLimit <= 0.3`。
4. 每次运动测试结束后发送零 Twist。

车端 ROS2 中可用的手工验证命令：

```bash
ros2 topic list | grep cmd_vel
ros2 topic echo /cmd_vel
```

低速短脉冲测试：

```bash
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.05, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
ros2 topic pub --once /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}"
```

## 10. 本地开发验证

控制台单元测试：

```powershell
cd D:\code\project\smart-car-remote-control-20260707\smart-car-console
npm test
```

前端构建：

```powershell
npm run build
```

无小车时也可以验证：

- `server/control.test.mjs`: 输入到 Twist 的转换。
- `server/keyboardDrive.test.mjs`: 键盘映射。

## 11. 常见修改任务

修改速度上限：

- 临时调参：改 UI 设置或 `local-config.json` 中 `control.maxLinearMps`、`control.maxAngularRps`。
- 改默认值：改 `smart-car-console/server/config.mjs` 中 `defaults.control`。
- 改转换逻辑：改 `smart-car-console/server/control.mjs`，并同步更新测试。

遥控转向与直行校正：

- `control.turnScale` 控制操作侧转向到 `/cmd_vel.angular.z` 的符号，当前默认为 `-1`，用于适配网页 A/D 和实车转向方向。
- `control.straightAssist` 只在前进/倒退且没有手动转向或横移输入时生效，使用 `/vel_raw.angular` 做小幅负反馈补偿。
- 现场验证直行校正时先低速，建议 `linearLimit <= 0.10`、`angularLimit <= 0.30`；如果补偿方向相反，优先调整 `straightAssist.feedbackSign`。

新增遥测 topic：

1. 在 `smart-car-console/server/rosbridge.mjs` 的 `subscriptions` 加 topic 和类型。
2. 增加解析函数。
3. 在 `smart-car-console/server/state.mjs` 增加 telemetry 状态字段。
4. 在 `smart-car-console/src/App.jsx` 增加显示。

修改键盘控制：

- 网页键盘：改 `smart-car-console/src/keyboardDrive.js`。
- 车端终端键盘：改 `ros2_car_remote_ws/src/icar_ctrl/icar_ctrl/icar_keyboard.py`。

修改手柄映射：

- X3：改 `ros2_car_remote_ws/src/icar_ctrl/icar_ctrl/icar_joy_X3.py`。
- R2：改 `ros2_car_remote_ws/src/icar_ctrl/icar_ctrl/icar_joy_R2.py`。

修改车端服务启动：

- 改 `smart-car-console/server/serviceManager.mjs` 中 `remoteStartScript()`、`remoteStatusScript()`、`remoteStopScript()`。
- 注意该文件中的命令是在小车 Jetson 上通过 SSH 执行，再进入 Docker 容器运行 ROS2。

## 12. 将 ROS2 改动部署到车端

车端路径因实验环境可能不同。当前控制台脚本假设 Docker 容器内存在：

```text
/root/icar_ros2_ws/icar_ws/install/setup.bash
/root/icar_ros2_ws/software/library_ws/install/setup.bash
```

推荐流程：

```powershell
scp -r .\ros2_car_remote_ws\src\icar_ctrl jetson@192.168.43.137:/home/jetson/remote_ws_src/
scp -r .\ros2_car_remote_ws\src\icar_bringup jetson@192.168.43.137:/home/jetson/remote_ws_src/
ssh jetson@192.168.43.137
```

在小车 Jetson 上：

```bash
docker ps
docker cp /home/jetson/remote_ws_src/icar_ctrl smartcar_icar_console:/root/icar_ros2_ws/icar_ws/src/icar_ctrl
docker cp /home/jetson/remote_ws_src/icar_bringup smartcar_icar_console:/root/icar_ros2_ws/icar_ws/src/icar_bringup
docker exec -it smartcar_icar_console bash
```

在容器内：

```bash
cd /root/icar_ros2_ws/icar_ws
source /opt/ros/foxy/setup.bash
colcon build --packages-select icar_ctrl icar_bringup
source install/setup.bash
ros2 run icar_ctrl icar_keyboard
```

如果容器名称不是 `smartcar_icar_console`，以 `docker ps` 输出为准。

## 13. 故障定位

SSH 失败：

- 确认电脑和小车在同一网段。
- `Test-NetConnection <car-ip> -Port 22`。
- 确认 `plinkPath` 正确。
- SSH host key 变化时，更新 `local-config.json` 或 UI 设置。

rosbridge 失败：

- 检查 `Test-NetConnection <car-ip> -Port 9090`。
- 点击控制台“启动服务”。
- 在车端容器内检查 `ros2 launch rosbridge_server rosbridge_websocket_launch.xml` 是否运行。

不能驾驶：

- 控制台 `canDrive` 需要底盘串口、雷达、相机或视频流、rosbridge 等状态满足。
- `server/state.mjs` 的 `recomputeCanDrive()` 定义了阻塞条件。
- 临时调试时不要直接删除安全阻塞，应先确认真实设备状态。

急停失败：

- 首选 rosbridge 连续发布零 Twist。
- 如果 rosbridge 断开，后端会用 SSH fallback 在容器内执行 `ros2 topic pub --once /cmd_vel ...`。
- 若 SSH 也失败，立即人工断电或取下小车。

## 14. AI 接手建议

优先按层定位：

- UI 问题先看 `src/App.jsx` 和 `src/styles.css`。
- 输入变 Twist 的问题先看 `server/control.mjs` 和对应测试。
- 连接、服务启动和端口状态问题先看 `server/serviceManager.mjs`。
- rosbridge 发布和遥测解析问题先看 `server/rosbridge.mjs`。
- 车端运动行为问题先看 `icar_ctrl` 和 `icar_bringup/Mcnamu_driver_X3.py`。

修改原则：

- 保持 `/cmd_vel` 合同稳定。
- 不把 `local-config.json`、日志或构建产物提交进项目。
- 对 motion-control 改动至少跑 `npm test`，物理测试前先零速度和低速短脉冲。
- 车端 ROS 包依赖不完整时，不要在 Windows 侧强行验证 ROS import；应在车端 Docker 或 ROS2 Foxy 环境中验证。

## 15. ROS2 安全导航闭环（2026-07-13）

当前可变车端地址是 `192.168.43.137`，必须以 `local-config.json` 或运行参数为准，不能把该地址当作永久设备身份。用户已恢复本地和车端非运动测试；任何非零 Twist、导航目标、巡航、返航或模拟低电返航仍需事先汇报并取得明确批准。

导航运行栈统一设置 `ROS_LOCALHOST_ONLY=1`，并通过 `fastdds_localhost.xml` 把 UDPv4 限定到 `127.0.0.1`、把 initial-peer range 扩为 64，以避免车端 host-network/Wi-Fi 和 participant churn 下的发现不完整。所有 ROS 节点和 rosbridge 都在同一容器网络命名空间；Windows 控制台只通过 9090 WebSocket 接入，不直接参与 DDS。

### 15.1 唯一速度链路

常规速度链路固定为：

```text
控制台 /cmd_vel_manual ─┐
                        ├─ cmd_vel_arbiter ─ /cmd_vel ─ X3 驱动
Nav2 /cmd_vel_nav ──────┘
```

- `cmd_vel_arbiter` 是 `/cmd_vel` 的唯一常规发布者；驱动发现发布者不唯一或名称不符时拒绝命令并归零。
- 急停/故障优先于人工，人工优先于导航；来源切换至少输出一个零周期。
- 人工接管会请求取消当前巡航，旧导航命令不会自动恢复。
- SSH 只保留向 `/cmd_vel` 发布一次零 Twist 的灾难恢复通道，禁止通过该通道发布非零命令。
- 驱动硬上限为 `linear.x/y <= 0.35 m/s`、`angular.z <= 0.80 rad/s`；控制台和导航默认先限制为 `0.05 m/s`、`0.20 rad/s`。只有低速验收通过后，才可在本地配置中提高到 `0.10 m/s`、`0.40 rad/s`。

### 15.2 新增状态与操作接口

状态 topic：

- `/control/active_source` (`std_msgs/msg/String`)
- `/safety/state` (`std_msgs/msg/String`)
- `/chassis/connected` (`std_msgs/msg/Bool`)
- `/patrol/status` (`std_msgs/msg/String`，JSON 状态心跳)
- `/alarm` (`car_interfaces/msg/Alarm`)
- `/alarm_events` (`std_msgs/msg/String`，兼容控制台)

操作接口：

- `/safety/estop` (`std_msgs/msg/Bool`)
- `/safety/reset`、`/safety/simulate_low_battery` (`std_srvs/srv/Trigger`)
- `/patrol/start`、`/patrol/cancel`、`/patrol/return_home` (`std_srvs/srv/Trigger`)

复位不是本地 UI 解锁：控制台先发送人工零命令和 `estop=false`，再调用 `/safety/reset`；只有车端返回 `success=true` 才清除本地急停显示。健康状态、TF、所有权、零输出或活动 action 任一不满足时，车端必须拒绝复位并保留原因。

### 15.3 互斥运行模式

`smart-car-console/local-config.json` 的 `navigation.mode` 只允许：

- `safe_base`：驱动、描述、雷达、IMU、EKF、仲裁和安全节点；没有 `map -> odom` 所有者。
- `mapping`：在 safe base 上仅由 Cartographer 发布 `map -> odom`。
- `navigation`：在 safe base 上仅由 AMCL 发布 `map -> odom`，并启动 NavFn、DWB、BT Navigator 和巡航管理器。
- `demo`：组合已验收的 navigation 与路线；`auto_start_patrol` 始终默认为 `false`。

切换模式时控制台会先停止旧导航相关进程。Cartographer 与 AMCL 同时存在、topic 所有者不唯一、TF 缺失或心跳陈旧都会锁存安全故障并保持零输出。雷达 frame 必须直接配置为 `laser_link`，禁止新增 `laser -> laser_link` 静态 TF 掩盖命名错误。

### 15.4 部署和证据

未来收到测试命令后，先审阅 dry-run；脚本不保存密码、不关闭 SSH host-key 校验，也不会自动启动运行节点：

```powershell
.\scripts\deploy_ros2_navigation.ps1 -CarIp 192.168.43.137 -DryRun
.\scripts\deploy_ros2_navigation.ps1 -CarIp 192.168.43.137 -UseConsoleConfig
```

`-UseConsoleConfig` 只在运行时读取已忽略的 `smart-car-console/local-config.json`，并在命令回显中隐藏密码和 host key；配置了 OpenSSH key 时可省略该开关。

部署使用不可变 release staging，仅在四个相关包构建（以及默认测试）成功后原子切换 overlay；失败时保留当前 overlay。`-SkipTests` 只用于明确的诊断场景，不能作为验收依据。

只读证据采集同样必须等用户下令后执行：

```powershell
.\scripts\collect_navigation_evidence.ps1 -CarIp 192.168.43.137 -Gate d1 -UseConsoleConfig
```

输出位于被忽略的 `artifacts/navigation/raw/`，不包含密码、host key 或 rosbag；脚本不会发布 Twist、调用服务或发送 action goal，也不会自行把门禁标为 PASS。

### 15.5 测试与运动批准

1. 当前阶段不连接小车、不运行本地或车端测试，等待用户进一步命令。
2. 恢复测试后，先完成纯逻辑、控制台、Foxy 构建和车端只读/零速度检查。
3. 任一需要或可能导致小车移动的测试，都必须先向用户汇报测试项、限速和场地要求，并等待明确批准；批准前不得发送非零 Twist、导航 goal、巡航或模拟低电返航请求。
4. 首次运动前确认轮子架空或场地清空，按 `0.05/0.20 -> 0.10/0.40` 分级；每个测试项结束都发送零 Twist。
5. D1-D4 严格顺序门禁，上一日没有完整证据 PASS 时不得进入下一日物理任务。

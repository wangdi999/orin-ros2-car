# 网页端建图与导航工作台

控制台左侧“建图与导航工作台”按以下五步操作。所有接口只监听 Windows 本机回环地址。

1. **建图**：显式切换 `mapping`，确认 Cartographer 与 `/map` 就绪，使用既有低速遥控覆盖区域，然后输入白名单地图名保存。保存是串行长操作，只生成候选地图，不会自动切换导航。
2. **地图**：校验 PGM、YAML、PBStream 非空及 YAML/PGM 元数据；查看栅格预览、下载三类文件、显式导入旧配置地图、激活、逻辑归档或恢复。当前激活地图禁止归档。
3. **定位**：激活地图后显式切换 `navigation`；在地图按下并拖动设置 X/Y/yaw，或精确输入数值，再发布标准 `/initialpose`。新鲜 AMCL/TF 到达后才显示定位就绪。
4. **单点导航**：在地图拖动设置目标或输入数值，经 `/navigation/send_goal` 交给唯一目标协调器。页面显示全局/局部路径、目标状态并始终提供取消入口。
5. **路线与巡航**：按地图保存一个 Home 和固定三个航点，可编辑停留、0–3 次重试、`skip|abort` 与循环。空闲时保存后调用 `/patrol/reload_route`；页面提供巡航、取消、返航和模拟低电。

## 存储与输入边界

- 车端地图：`/home/jetson/maps`，容器：`/root/maps`
- 车端路线：`/home/jetson/routes/<mapId>.yaml`，容器：`/root/routes/<mapId>.yaml`
- 地图名仅允许 `[A-Za-z0-9_-]{1,64}`；网页不接受任意文件路径或 shell 文本。
- 地图归档使用 `/home/jetson/maps/.archive-index/<mapId>` 标记，不永久删除地图文件。
- 地图保存、模式切换返回 HTTP 202 与 `operationId`；同一时刻只允许一个工作流操作。
- 地图激活只允许在 `safe_base` 或 `mapping` 模式执行，避免配置已经指向新地图而正在运行的 Nav2 仍使用旧地图；激活后再显式切换到 `navigation`。
- 模式切换或地图保存运行期间拒绝新的非零遥控、单点目标、巡航、返航和低电量模拟；取消、零命令与急停始终可用。地图保存前会先请求重复零速。
- 空白或 `null` 的 X/Y/yaw 不会被当作零坐标；Home 与三个航点必须全部填写后才能保存为可执行路线。

首次进入运动功能时必须确认风险提示，确认时间只写入被忽略的本地私有配置。设置页可重置提示。此门禁覆盖非零遥控、单点目标、巡航、返航和模拟低电，但不阻止零命令、取消和手动急停。

## 控制台心跳与手动急停

Windows 控制台心跳、浏览器遥测 WebSocket 或 ROSBridge 连接超时时，控制台只执行重复零速度请求并产生严重告警，不自动发布 `/safety/estop=true`，因此不会因网页心跳超时形成需要人工复位的急停锁存。急停锁存由网页急停按钮、空格键或显式 `POST /api/emergency-stop` 触发。

车端驱动 300 ms watchdog、速度仲裁器陈旧状态归零和安全管理器的硬件故障锁存没有被禁用。它们仍在控制台失联时 fail closed，不能通过网页关闭。

## 本地 HTTP 接口

- `POST /api/navigation/mode`、`GET /api/navigation/operations/current`
- `GET /api/maps`、`POST /api/maps/save`、`POST /api/maps/import-active`
- `POST /api/maps/:id/verify|activate|archive|restore`
- `GET /api/maps/:id/preview`、`GET /api/maps/:id/files/:ext`
- `GET|PUT /api/routes/:mapId`
- `POST /api/localization/initial-pose`
- `POST /api/navigation/goals`、`DELETE /api/navigation/goals/current`
- `POST|DELETE /api/safety/motion-warning/ack`
- 既有 `POST /api/patrol/start|cancel|return-home`、`POST /api/safety/simulate-low-battery`

JSON 响应统一包含 `ok`、`code`、`message`、`blockers` 和 `state`。部署后的非运动检查不得发送目标、巡航、返航或非零 Twist；物理验收仍需现场明确批准。

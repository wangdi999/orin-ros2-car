# 项目记忆

## Python 版本策略
- smart_car_ws / ros2_agent_ws / ros2_car_remote_ws → Python 3.8（系统默认）
- agent-runtime → Python 3.13（需要 Python 3.10+ 的联合类型语法 `|`）

## 测试策略
- **离线 mock 测试**: 在无 ROS2/GPU 的 Windows 开发环境，通过 mock `sys.modules` 测试核心逻辑
- **必须 ROS2 环境的测试**: 完整 ROS2 节点（如 AIWebBridgeNode 继承 rclpy.Node）需要源码级别静态测试
- **ROS2 lint 测试** (ament_copyright/flake8/pep257): 仅在 ROS2 环境运行，全量测试脚本中排除

## 安全规则（来自 AGENTS.md）
- 不要发送运动命令除非用户明确要求物理车测试
- 物理测试前提示用户抬起车轮或清理区域
- 使用低速限制: linear 0.05-0.10 m/s, angular 0.2-0.4 rad/s
- 任何运动测试后发送 zero Twist

## 修复过的典型问题
- bbox 坐标顺序: 必须 (x1,y1,x2,y2) 且 y1<y2, x1<x2，否则 IoU 计算始终为 0
- mock rclpy.Node 子类: 避免 mock `__init__`，改为直接测试核心逻辑函数

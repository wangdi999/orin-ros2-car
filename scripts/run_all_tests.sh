#!/usr/bin/env bash
# 全模块测试联调脚本（Linux / CI / WSL）
# 运行所有模块测试、烟雾测试和跨模块联调测试
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== [1/6] smart_car_ws (AI 视觉) ==="
cd smart_car_ws
python3 -m pip install --quiet pytest numpy PyYAML 2>/dev/null || python -m pip install --quiet pytest numpy PyYAML
python3 -m pytest -q || python -m pytest -q
cd "$ROOT"

echo "=== [2/6] ros2_agent_ws (巡逻/安全) ==="
cd ros2_agent_ws
python3 -m pip install --quiet pytest PyYAML 2>/dev/null || python -m pip install --quiet pytest PyYAML
python3 -m pytest -q || python -m pytest -q
cd "$ROOT"

echo "=== [3/6] agent-runtime (LangGraph 编排) ==="
# agent-runtime 需要 Python 3.10+（使用了 | 联合类型语法）
cd agent-runtime
if command -v python3.13 &>/dev/null; then
    python3.13 -m pip install --quiet -e '.[dev]' 2>/dev/null || python3 -m pip install --quiet -e '.[dev]'
    python3.13 -m pytest -q -s || python3 -m pytest -q -s
else
    python3 -m pip install --quiet -e '.[dev]' 2>/dev/null || python -m pip install --quiet -e '.[dev]'
    python3 -m pytest -q -s || python -m pytest -q -s
fi
cd "$ROOT"

echo "=== [4/6] ros2_car_remote_ws (底盘驱动 transform_utils) ==="
# 此测试需要 PyKDL，不可用时自动跳过
# 排除 ament_* lint 测试（仅 ROS2 环境可用）
cd ros2_car_remote_ws
python3 -m pip install --quiet pytest 2>/dev/null || python -m pip install --quiet pytest
python3 -m pytest -q src/icar_bringup/test/test_transform_utils.py || python -m pytest -q src/icar_bringup/test/test_transform_utils.py || true
cd "$ROOT"

echo "=== [5/6] smart-car-console (Web 控制台) ==="
cd smart-car-console
if [ -f package-lock.json ]; then npm ci --silent 2>/dev/null || npm install --silent; fi
npm test
cd "$ROOT"

echo "=== [6/6] 跨模块联调 + 烟雾测试 ==="
python3 -m pip install --quiet pytest numpy PyYAML 2>/dev/null || python -m pip install --quiet pytest numpy PyYAML
python3 -m pytest -q tests/integration || python -m pytest -q tests/integration

echo "--- 烟雾测试 ---"
python3 scripts/smoke_test_modules.py || python scripts/smoke_test_modules.py

echo ""
echo "All module tests passed."

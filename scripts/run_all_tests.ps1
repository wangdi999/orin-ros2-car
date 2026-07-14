# 全模块测试联调脚本（Windows PowerShell）
# 运行所有模块测试、烟雾测试和跨模块联调测试
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Pytest($WorkDir, $ExtraArgs = @()) {
    Push-Location $WorkDir
    try {
        python -m pip install --quiet pytest numpy PyYAML 2>$null
        python -m pytest -q @ExtraArgs
        if ($LASTEXITCODE -ne 0) { throw "pytest failed in $WorkDir" }
    } finally {
        Pop-Location
    }
}

Write-Host "=== [1/6] smart_car_ws (AI 视觉) ==="
Invoke-Pytest (Join-Path $Root "smart_car_ws") @("src/")

Write-Host "=== [2/6] ros2_agent_ws (巡逻/安全) ==="
Invoke-Pytest (Join-Path $Root "ros2_agent_ws") @("src/")

Write-Host "=== [3/6] agent-runtime (LangGraph 编排) ==="
# agent-runtime 需要 Python 3.10+（使用了 | 联合类型语法）
Push-Location (Join-Path $Root "agent-runtime")
try {
    # 尝试用 Python 3.13 运行，回退到默认 Python
    $py = if (Get-Command python3.13 -ErrorAction SilentlyContinue) { "python3.13" } else { "python" }
    & $py -m pip install --quiet -e ".[dev]" 2>$null
    & $py -m pytest -q -s
    if ($LASTEXITCODE -ne 0) { throw "agent-runtime pytest failed" }
} finally {
    Pop-Location
}

Write-Host "=== [4/6] ros2_car_remote_ws (底盘驱动 transform_utils) ==="
# 此测试需要 PyKDL，不可用时自动跳过
# 排除 ament_* lint 测试（仅 ROS2 环境可用）
Push-Location (Join-Path $Root "ros2_car_remote_ws")
try {
    python -m pytest -q src/icar_bringup/test/test_transform_utils.py
    if ($LASTEXITCODE -ne 0) { throw "icar_bringup pytest failed" }
} finally {
    Pop-Location
}

Write-Host "=== [5/6] smart-car-console (Web 控制台) ==="
Push-Location (Join-Path $Root "smart-car-console")
try {
    if (Test-Path "package-lock.json") {
        npm ci --silent 2>$null
    } else {
        npm install --silent 2>$null
    }
    npm test
    if ($LASTEXITCODE -ne 0) { throw "smart-car-console tests failed" }
} finally {
    Pop-Location
}

Write-Host "=== [6/6] 跨模块联调 + 烟雾测试 ==="
Invoke-Pytest $Root @("tests/integration")

Write-Host "--- 烟雾测试 ---"
Push-Location $Root
try {
    python scripts/smoke_test_modules.py
    if ($LASTEXITCODE -ne 0) { throw "smoke test failed" }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "All module tests passed."

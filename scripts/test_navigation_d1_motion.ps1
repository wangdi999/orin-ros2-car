[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet(
        'preflight',
        'linear',
        'angular',
        'timeout',
        'source_switch',
        'estop',
        'driver_sigterm'
    )]
    [string]$Scenario,
    [Parameter(Mandatory)]
    [switch]$ApprovedAreaClearAndEstopReady,
    [string]$CarIp = '192.168.43.137',
    [string]$ContainerName = 'smartcar_icar_console',
    [string]$ConsoleConfigPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $ApprovedAreaClearAndEstopReady) {
    throw 'D1 motion tests require explicit area-clear and emergency-stop approval.'
}
if ($CarIp -notmatch '^[A-Za-z0-9.-]+$') {
    throw 'CarIp contains unsupported characters.'
}
if ($ContainerName -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'ContainerName contains unsupported characters.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ConsoleConfigPath)) {
    $ConsoleConfigPath = Join-Path $repositoryRoot 'smart-car-console\local-config.json'
}
if (-not (Test-Path -LiteralPath $ConsoleConfigPath -PathType Leaf)) {
    throw "Private console config was not found: $ConsoleConfigPath"
}

$privateConfig = Get-Content -LiteralPath $ConsoleConfigPath -Raw -Encoding UTF8 |
    ConvertFrom-Json
$plinkPath = [string]$privateConfig.car.plinkPath
$pscpPath = Join-Path (Split-Path -Parent $plinkPath) 'pscp.exe'
$password = [string]$privateConfig.car.sshPassword
$hostKey = [string]$privateConfig.car.sshHostKey
$sshUser = [string]$privateConfig.car.sshUser
if (-not (Test-Path -LiteralPath $plinkPath -PathType Leaf)) {
    throw 'Configured plink executable was not found.'
}
if (-not (Test-Path -LiteralPath $pscpPath -PathType Leaf)) {
    throw 'pscp.exe was not found next to the configured plink executable.'
}
if ([string]::IsNullOrWhiteSpace($password) -or
        [string]::IsNullOrWhiteSpace($hostKey) -or
        [string]::IsNullOrWhiteSpace($sshUser)) {
    throw 'Console config must contain SSH user, password and host key.'
}

$probePath = Join-Path $PSScriptRoot 'ros_d1_motion_probe.py'
$probeSource = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8
if ($probeSource -notmatch "APPROVAL_TOKEN = 'AREA_CLEAR_AND_ESTOP_READY'" -or
        $probeSource -notmatch 'LINEAR_LIMIT = 0\.10' -or
        $probeSource -notmatch 'ANGULAR_LIMIT = 0\.40' -or
        $probeSource -notmatch 'LINEAR_PULSE_SEC = 2\.00' -or
        $probeSource -notmatch 'ANGULAR_PULSE_SEC = 2\.00' -or
        $probeSource -notmatch 'def finish_zero\(self\)') {
    throw 'D1 motion probe safety constants or zero cleanup are missing.'
}
function Invoke-PrivateRemoteScript {
    param([Parameter(Mandatory)][string]$Script)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $target = "$sshUser@$CarIp"
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $plinkPath -ssh -batch -hostkey $hostKey -pw $password `
            $target $remoteCommand 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return [pscustomobject]@{
        code = $exitCode
        text = (($output | ForEach-Object { [string]$_ }) -join `
            [Environment]::NewLine)
    }
}

$innerCommon = @'
set -eo pipefail
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
export PYTHONUNBUFFERED=1

probe=/tmp/ros_d1_motion_probe.py
zero='{linear: {x: 0.0, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.0}}'
cleanup() {
  # A manual zero is sufficient to stop the sole arbiter. Publishing a fresh
  # navigation zero immediately afterward would intentionally latch the
  # manual-takeover navigation inhibit and contaminate the next test case.
  timeout 3 ros2 topic pub --once /cmd_vel_manual geometry_msgs/msg/Twist "$zero" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
'@

if ($Scenario -eq 'driver_sigterm') {
    $inner = $innerCommon + @'

result=/tmp/d1_driver_sigterm_result.txt
trigger=/tmp/d1_driver_sigterm_trigger.txt
rm -f "$result" "$trigger"

target_pids=()
while read -r candidate; do
  [ -n "$candidate" ] || continue
  state="$(awk '{print $3}' "/proc/$candidate/stat" 2>/dev/null || true)"
  [ -n "$state" ] && [ "$state" != 'Z' ] || continue
  owns_device=0
  for fd in "/proc/$candidate/fd"/*; do
    target="$(readlink "$fd" 2>/dev/null || true)"
    if [ "$target" = '/dev/myserial' ]; then
      owns_device=1
      break
    fi
  done
  [ "$owns_device" -eq 1 ] || continue
  target_pids+=("$candidate")
done < <(pgrep -f '/icar_bringup/Mcnamu_driver_X3 --ros-args' || true)
if [ "${#target_pids[@]}" -ne 1 ]; then
  printf 'Expected one live chassis driver, found %s\n' "${#target_pids[@]}" >&2
  exit 32
fi

timeout --signal=TERM 25 python3 "$probe" \
  --approval-token AREA_CLEAR_AND_ESTOP_READY \
  --scenario external_fault \
  --expected-state CHASSIS_FAULT \
  --trigger-file "$trigger" >"$result" 2>&1 &
probe_pid=$!
ready=0
for _ in $(seq 1 160); do
  if grep -q '^READY_FOR_FAULT$' "$result" 2>/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "$probe_pid" 2>/dev/null; then
    break
  fi
  sleep 0.05
done
if [ "$ready" -ne 1 ]; then
  wait "$probe_pid" || true
  cat "$result"
  exit 33
fi

date +%s.%N > "$trigger"
kill -TERM "${target_pids[0]}"
set +e
wait "$probe_pid"
status=$?
set -e
cat "$result"
exit "$status"
'@
} else {
    $inner = $innerCommon + @'

timeout --signal=TERM 25 python3 "$probe" \
  --approval-token AREA_CLEAR_AND_ESTOP_READY \
  --scenario '__SCENARIO__'
'@
    $inner = $inner.Replace('__SCENARIO__', $Scenario)
}

$innerEncoded = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($inner))
$outer = @'
set -euo pipefail
cid="$(docker ps -q --filter 'name=__CONTAINER__' | head -n 1)"
if [ -z "$cid" ]; then
  echo 'Required ROS container is not running' >&2
  exit 20
fi
docker cp /home/jetson/ros_d1_motion_probe.py "$cid:/tmp/ros_d1_motion_probe.py"
docker exec "$cid" bash -lc "printf '%s' '__INNER__' | base64 -d | bash"
'@
$outer = $outer.Replace('__CONTAINER__', $ContainerName)
$outer = $outer.Replace('__INNER__', $innerEncoded)

Write-Host "Running approved D1 scenario '$Scenario' at 0.10 m/s / 0.40 rad/s ceilings"
$target = "$sshUser@$CarIp`:/home/jetson/ros_d1_motion_probe.py"
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    & $pscpPath -batch -hostkey $hostKey -pw $password -q `
        $probePath $target 2>&1 | Out-Null
    $copyExitCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $previousErrorAction
}
if ($copyExitCode -ne 0) {
    throw "Could not stage D1 motion probe on the target (exit $copyExitCode)."
}
$result = Invoke-PrivateRemoteScript -Script $outer
if (-not [string]::IsNullOrWhiteSpace($result.text)) {
    Write-Output $result.text
}

$captureId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$artifactDirectory = Join-Path $repositoryRoot `
    "artifacts\navigation\raw\$captureId-d1-motion"
[IO.Directory]::CreateDirectory($artifactDirectory) | Out-Null
$artifactPath = Join-Path $artifactDirectory "$Scenario.txt"
[IO.File]::WriteAllText(
    $artifactPath,
    $result.text + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false))
Write-Host "Raw motion evidence: $artifactPath"

if ($Scenario -eq 'driver_sigterm' -or $result.code -ne 0) {
    Write-Host 'Restoring clean safe-base after process interruption/failure'
    & (Join-Path $PSScriptRoot 'test_navigation_non_motion_fault.ps1') `
        -Scenario chassis `
        -CarIp $CarIp `
        -ContainerName $ContainerName `
        -ConsoleConfigPath $ConsoleConfigPath `
        -RestoreOnly
}

if ($result.code -ne 0) {
    throw "D1 scenario '$Scenario' failed with exit code $($result.code)."
}
if ($Scenario -eq 'preflight') {
    Write-Host 'D1 preflight passed without publishing any non-zero command.'
} else {
    Write-Host "D1 scenario '$Scenario' passed and ended with explicit zero commands."
}

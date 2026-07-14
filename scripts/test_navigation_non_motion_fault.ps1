[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('lidar', 'odom', 'chassis')]
    [string]$Scenario,
    [string]$CarIp = '',
    [string]$ContainerName = 'smartcar_icar_console',
    [string]$ConsoleConfigPath = '',
    [ValidateRange(0.05, 0.10)]
    [double]$MaxLinear = 0.05,
    [ValidateRange(0.20, 0.40)]
    [double]$MaxAngular = 0.20,
    [switch]$RestoreOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ConsoleConfigPath)) {
    $ConsoleConfigPath = Join-Path $repositoryRoot 'smart-car-console\local-config.json'
}
if (-not (Test-Path -LiteralPath $ConsoleConfigPath -PathType Leaf)) {
    throw "Private console config was not found: $ConsoleConfigPath"
}
if ($ContainerName -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'ContainerName contains unsupported characters.'
}

$privateConfig = Get-Content -LiteralPath $ConsoleConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($CarIp)) {
    $CarIp = [string]$privateConfig.car.host
}
if ($CarIp -notmatch '^[A-Za-z0-9.-]+$') {
    throw 'CarIp is missing or contains unsupported characters.'
}
$plinkPath = [string]$privateConfig.car.plinkPath
$password = [string]$privateConfig.car.sshPassword
$hostKey = [string]$privateConfig.car.sshHostKey
$sshUser = [string]$privateConfig.car.sshUser
if (-not (Test-Path -LiteralPath $plinkPath -PathType Leaf)) {
    throw 'Configured plink executable was not found.'
}
if ([string]::IsNullOrWhiteSpace($password) -or
        [string]::IsNullOrWhiteSpace($hostKey) -or
        [string]::IsNullOrWhiteSpace($sshUser)) {
    throw 'Console config must contain SSH user, password and host key.'
}

$probePath = Join-Path $PSScriptRoot 'ros_safety_state_probe.py'
$probeSource = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8
if ($probeSource -match '(?i)create_publisher|create_client|ActionClient|publish\s*\(') {
    throw 'Read-only state probe contains an output-capable ROS API.'
}
$probeEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probeSource))

$scenarios = @{
    lidar = @{
        expected = 'SENSOR_FAULT'
        process = '/sllidar_ros2/sllidar_node --ros-args'
        requiredDevice = ''
    }
    odom = @{
        expected = 'ODOM_TF_FAULT'
        process = '/robot_localization/ekf_node --ros-args'
        requiredDevice = ''
    }
    chassis = @{
        expected = 'CHASSIS_FAULT'
        process = '/icar_bringup/Mcnamu_driver_X3 --ros-args'
        requiredDevice = '/dev/myserial'
    }
}
$selected = $scenarios[$Scenario]

function Invoke-PrivateRemoteScript {
    param([Parameter(Mandatory)][string]$Script)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $target = "$sshUser@$CarIp"
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $plinkPath -ssh -batch -hostkey $hostKey -pw $password $target $remoteCommand 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    return [pscustomobject]@{
        code = $exitCode
        text = (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
    }
}

$faultInner = @'
set -eo pipefail
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
export PYTHONUNBUFFERED=1

probe=/tmp/ros_safety_state_probe.py
result=/tmp/non_motion_fault_result.txt
trigger=/tmp/non_motion_fault_trigger.txt
rm -f "$result" "$trigger"
printf '%s' '__PROBE__' | base64 -d > "$probe"
python3 "$probe" \
  --expected-state '__EXPECTED__' \
  --trigger-file "$trigger" \
  --require-initial-ready \
  --initial-timeout-sec 4 \
  --timeout-sec 5 > "$result" 2>&1 &
probe_pid=$!

ready=0
for _ in $(seq 1 100); do
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
  exit 31
fi

target_pids=()
while read -r candidate; do
  [ -n "$candidate" ] || continue
  state="$(awk '{print $3}' "/proc/$candidate/stat" 2>/dev/null || true)"
  [ -n "$state" ] && [ "$state" != 'Z' ] || continue
  if [ -n '__REQUIRED_DEVICE__' ]; then
    owns_required_device=0
    for fd in "/proc/$candidate/fd"/*; do
      target="$(readlink "$fd" 2>/dev/null || true)"
      if [ "$target" = '__REQUIRED_DEVICE__' ]; then
        owns_required_device=1
        break
      fi
    done
    [ "$owns_required_device" -eq 1 ] || continue
  fi
  target_pids+=("$candidate")
done < <(pgrep -f '__PROCESS__' || true)
if [ "${#target_pids[@]}" -ne 1 ]; then
  printf 'Expected one live target process, found %s\n' "${#target_pids[@]}" >&2
  printf '%s\n' "${target_pids[@]:-}" >&2
  kill "$probe_pid" 2>/dev/null || true
  wait "$probe_pid" 2>/dev/null || true
  exit 32
fi

date +%s.%N > "$trigger"
kill -TERM "${target_pids[0]}"
set +e
wait "$probe_pid"
probe_status=$?
set -e
cat "$result"
exit "$probe_status"
'@
$faultInner = $faultInner.Replace('__PROBE__', $probeEncoded)
$faultInner = $faultInner.Replace('__EXPECTED__', [string]$selected.expected)
$faultInner = $faultInner.Replace('__PROCESS__', [string]$selected.process)
$faultInner = $faultInner.Replace('__REQUIRED_DEVICE__', [string]$selected.requiredDevice)
$faultInnerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($faultInner))

$faultOuter = @'
set -euo pipefail
cid="$(docker ps -q --filter 'name=__CONTAINER__' | head -n 1)"
if [ -z "$cid" ]; then
  echo 'Required ROS container is not running' >&2
  exit 20
fi
docker exec "$cid" bash -lc "printf '%s' '__INNER__' | base64 -d | bash"
'@
$faultOuter = $faultOuter.Replace('__CONTAINER__', $ContainerName)
$faultOuter = $faultOuter.Replace('__INNER__', $faultInnerEncoded)

$restartInner = @'
set -e
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
exec ros2 launch icar_navigation safe_base.launch.py \
  max_linear:=__MAX_LINEAR__ max_angular:=__MAX_ANGULAR__ lidar_frame:=laser_link \
  >/tmp/smartcar_navigation.log 2>&1
'@
$restartInner = $restartInner.Replace(
    '__MAX_LINEAR__',
    $MaxLinear.ToString([Globalization.CultureInfo]::InvariantCulture))
$restartInner = $restartInner.Replace(
    '__MAX_ANGULAR__',
    $MaxAngular.ToString([Globalization.CultureInfo]::InvariantCulture))
$restartInnerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($restartInner))

$rosbridgeInner = @'
set -e
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
  >/tmp/smartcar_rosbridge.log 2>&1
'@
$rosbridgeInnerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($rosbridgeInner))

$readyInner = @'
set -e
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
printf '%s' '__PROBE__' | base64 -d | timeout --signal=KILL 20 python3 - \
  --expected-state READY --timeout-sec 12 --settle-sec 0.50
'@
$readyInner = $readyInner.Replace('__PROBE__', $probeEncoded)
$readyInnerEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($readyInner))

$restoreOuter = @'
set -euo pipefail
cid="$(docker ps -q --filter 'name=__CONTAINER__' | head -n 1)"
if [ -z "$cid" ]; then
  echo 'Required ROS container is not running' >&2
  exit 20
fi
docker restart -t 2 "$cid" >/dev/null
sleep 1
docker exec -d "$cid" bash -lc "printf '%s' '__RESTART__' | base64 -d | bash"
docker exec -d "$cid" bash -lc "printf '%s' '__ROSBRIDGE__' | base64 -d | bash"
sleep 7
docker exec "$cid" bash -lc "printf '%s' '__READY__' | base64 -d | bash"
'@
$restoreOuter = $restoreOuter.Replace('__CONTAINER__', $ContainerName)
$restoreOuter = $restoreOuter.Replace('__RESTART__', $restartInnerEncoded)
$restoreOuter = $restoreOuter.Replace('__ROSBRIDGE__', $rosbridgeInnerEncoded)
$restoreOuter = $restoreOuter.Replace('__READY__', $readyInnerEncoded)

if (-not $RestoreOnly) {
    Write-Host "Running zero-output $Scenario process-fault check"
    $faultResult = Invoke-PrivateRemoteScript -Script $faultOuter
    if (-not [string]::IsNullOrWhiteSpace($faultResult.text)) {
        Write-Output $faultResult.text
    }
}

Write-Host 'Restoring safe-base and checking READY/zero output'
$restoreResult = Invoke-PrivateRemoteScript -Script $restoreOuter
if (-not [string]::IsNullOrWhiteSpace($restoreResult.text)) {
    Write-Output $restoreResult.text
}

if ($restoreResult.code -ne 0) {
    throw "Safe-base restoration failed with exit code $($restoreResult.code)."
}
if (-not $RestoreOnly -and $faultResult.code -ne 0) {
    throw "$Scenario fault check failed with exit code $($faultResult.code)."
}

if ($RestoreOnly) {
    Write-Host 'Safe-base cleanup/restoration passed.'
} else {
    Write-Host "$Scenario non-motion fault check passed; safe-base is restored."
}

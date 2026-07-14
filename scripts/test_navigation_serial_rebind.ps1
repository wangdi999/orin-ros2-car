[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('dry_run', 'moving')]
    [string]$Mode,
    [switch]$ApprovedAreaClearAndEstopReady,
    [string]$CarIp = '',
    [string]$ContainerName = 'smartcar_icar_console',
    [string]$ConsoleConfigPath = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($Mode -eq 'moving' -and -not $ApprovedAreaClearAndEstopReady) {
    throw 'Moving serial-rebind tests require explicit area-clear approval.'
}
if ($ContainerName -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'ContainerName contains unsupported characters.'
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ConsoleConfigPath)) {
    $ConsoleConfigPath = Join-Path `
        $repositoryRoot 'smart-car-console\local-config.json'
}
$privateConfig = Get-Content -LiteralPath $ConsoleConfigPath `
    -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace($CarIp)) {
    $CarIp = [string]$privateConfig.car.host
}
if ($CarIp -notmatch '^[A-Za-z0-9.-]+$') {
    throw 'CarIp is missing or contains unsupported characters.'
}
$plinkPath = [string]$privateConfig.car.plinkPath
$pscpPath = Join-Path (Split-Path -Parent $plinkPath) 'pscp.exe'
$password = [string]$privateConfig.car.sshPassword
$hostKey = [string]$privateConfig.car.sshHostKey
$sshUser = [string]$privateConfig.car.sshUser
if (-not (Test-Path -LiteralPath $plinkPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $pscpPath -PathType Leaf)) {
    throw 'Configured plink/pscp executables were not found.'
}
if ([string]::IsNullOrWhiteSpace($password) -or
        [string]::IsNullOrWhiteSpace($hostKey) -or
        [string]::IsNullOrWhiteSpace($sshUser)) {
    throw 'Console config must contain private SSH connection fields.'
}

$motionProbePath = Join-Path $PSScriptRoot 'ros_d1_motion_probe.py'
$stateProbePath = Join-Path $PSScriptRoot 'ros_safety_state_probe.py'
$recoveryProbePath = Join-Path `
    $PSScriptRoot 'ros_chassis_recovery_probe.py'
$motionProbeSource = Get-Content -LiteralPath $motionProbePath `
    -Raw -Encoding UTF8
$stateProbeSource = Get-Content -LiteralPath $stateProbePath `
    -Raw -Encoding UTF8
$recoveryProbeSource = Get-Content -LiteralPath $recoveryProbePath `
    -Raw -Encoding UTF8
if (($stateProbeSource + $recoveryProbeSource) -match `
        '(?i)create_publisher|create_client|ActionClient|publish\s*\(') {
    throw 'Read-only state probe contains an output-capable ROS API.'
}

function Invoke-PrivateRemoteScript {
    param([Parameter(Mandatory)][string]$Script)
    $encoded = [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes($Script))
    $target = "$sshUser@$CarIp"
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = & $plinkPath -ssh -batch -hostkey $hostKey `
            -pw $password $target $remoteCommand 2>&1
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

$probeInnerCommon = @'
set -eo pipefail
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
export PYTHONUNBUFFERED=1
rm -f /tmp/serial_rebind_trigger /tmp/serial_rebind_result
'@

if ($Mode -eq 'moving') {
    $probeInner = $probeInnerCommon + @'

timeout --signal=TERM 35 python3 /tmp/ros_d1_motion_probe.py \
  --approval-token AREA_CLEAR_AND_ESTOP_READY \
  --scenario external_fault \
  --expected-state CHASSIS_FAULT \
  --trigger-file /tmp/serial_rebind_trigger \
  >/tmp/serial_rebind_result 2>&1 &
probe_pid=$!
for _ in $(seq 1 200); do
  grep -q '^READY_FOR_FAULT$' /tmp/serial_rebind_result 2>/dev/null && break
  kill -0 "$probe_pid" 2>/dev/null || break
  sleep 0.05
done
if ! grep -q '^READY_FOR_FAULT$' /tmp/serial_rebind_result 2>/dev/null; then
  wait "$probe_pid" || true
  cat /tmp/serial_rebind_result
  exit 31
fi
echo READY_FOR_SERIAL_REBIND
set +e
wait "$probe_pid"
status=$?
set -e
cat /tmp/serial_rebind_result
exit "$status"
'@
} else {
    $probeInner = $probeInnerCommon + @'

timeout --signal=TERM 25 python3 /tmp/ros_safety_state_probe.py \
  --expected-state CHASSIS_FAULT \
  --trigger-file /tmp/serial_rebind_trigger \
  --require-initial-ready --initial-timeout-sec 6 --timeout-sec 8 \
  >/tmp/serial_rebind_result 2>&1 &
probe_pid=$!
for _ in $(seq 1 160); do
  grep -q '^READY_FOR_FAULT$' /tmp/serial_rebind_result 2>/dev/null && break
  kill -0 "$probe_pid" 2>/dev/null || break
  sleep 0.05
done
if ! grep -q '^READY_FOR_FAULT$' /tmp/serial_rebind_result 2>/dev/null; then
  wait "$probe_pid" || true
  cat /tmp/serial_rebind_result
  exit 31
fi
echo READY_FOR_SERIAL_REBIND
set +e
wait "$probe_pid"
status=$?
set -e
cat /tmp/serial_rebind_result
exit "$status"
'@
}
$probeInnerEncoded = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($probeInner))

$recoveryInner = @'
set -e
source /opt/ros/foxy/setup.bash
source /root/icar_ros2_ws/icar_ws/install/setup.bash
source /root/icar_ros2_ws/software/library_ws/install/setup.bash
source /root/ros2_navigation_overlay/install/setup.bash
export ROS_LOCALHOST_ONLY=1
export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
timeout --signal=KILL 22 python3 /tmp/ros_chassis_recovery_probe.py \
  --timeout-sec 16
timeout 6 ros2 service call /safety/reset std_srvs/srv/Trigger '{}'
timeout --signal=KILL 10 python3 /tmp/ros_safety_state_probe.py \
  --expected-state READY --timeout-sec 6 --settle-sec 0.75
'@
$recoveryInnerEncoded = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($recoveryInner))

$outer = @'
set -euo pipefail
cid="$(docker ps -q --filter 'name=__CONTAINER__' | head -n 1)"
test -n "$cid"
test -e /dev/myserial
tty="$(basename "$(readlink -f /dev/myserial)")"
case "$tty" in ttyUSB[0-9]*) ;; *) echo 'Unexpected serial tty' >&2; exit 40;; esac
interface_path="$(readlink -f "/sys/class/tty/$tty/device/..")"
interface="$(basename "$interface_path")"
driver="$(basename "$(readlink -f "$interface_path/driver")")"
case "$interface" in *:*.*) ;; *) echo 'Unexpected USB interface' >&2; exit 41;; esac
if [ "$driver" != ch341 ]; then
  echo "Refusing to unbind unexpected driver: $driver" >&2
  exit 42
fi
unbind="/sys/bus/usb/drivers/$driver/unbind"
bind="/sys/bus/usb/drivers/$driver/bind"
test -e "$unbind" && test -e "$bind"
sudo -n true

docker cp /home/jetson/ros_d1_motion_probe.py \
  "$cid:/tmp/ros_d1_motion_probe.py"
docker cp /home/jetson/ros_safety_state_probe.py \
  "$cid:/tmp/ros_safety_state_probe.py"
docker cp /home/jetson/ros_chassis_recovery_probe.py \
  "$cid:/tmp/ros_chassis_recovery_probe.py"

log=/tmp/serial_rebind_outer.log
rm -f "$log"
unbound=0
restore_binding() {
  if [ "$unbound" -eq 1 ]; then
    sudo sh -c "printf '%s' '$interface' > '$bind'" || true
    unbound=0
    udevadm settle || true
  fi
}
trap restore_binding EXIT INT TERM

docker exec "$cid" bash -lc \
  "printf '%s' '__PROBE_INNER__' | base64 -d | bash" >"$log" 2>&1 &
observer_pid=$!
ready=0
for _ in $(seq 1 240); do
  if grep -q '^READY_FOR_SERIAL_REBIND$' "$log" 2>/dev/null; then
    ready=1
    break
  fi
  kill -0 "$observer_pid" 2>/dev/null || break
  sleep 0.05
done
if [ "$ready" -ne 1 ]; then
  wait "$observer_pid" || true
  cat "$log"
  exit 43
fi

trigger="$(date +%s.%N)"
docker exec "$cid" sh -c \
  "printf '%s' '$trigger' > /tmp/serial_rebind_trigger"
sudo sh -c "printf '%s' '$interface' > '$unbind'"
unbound=1
sleep 1
sudo sh -c "printf '%s' '$interface' > '$bind'"
unbound=0
udevadm settle

set +e
wait "$observer_pid"
observer_status=$?
set -e
cat "$log"
if [ "$observer_status" -ne 0 ]; then
  exit "$observer_status"
fi

for _ in $(seq 1 80); do
  [ -e /dev/myserial ] && break
  sleep 0.10
done
test -e /dev/myserial
sleep 5
docker exec "$cid" bash -lc \
  "printf '%s' '__RECOVERY_INNER__' | base64 -d | bash"
'@
$outer = $outer.Replace('__CONTAINER__', $ContainerName)
$outer = $outer.Replace('__PROBE_INNER__', $probeInnerEncoded)
$outer = $outer.Replace('__RECOVERY_INNER__', $recoveryInnerEncoded)

$targetPrefix = "$sshUser@$CarIp`:/home/jetson"
foreach ($probePath in @(
        $motionProbePath, $stateProbePath, $recoveryProbePath)) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $pscpPath -batch -hostkey $hostKey -pw $password -q `
            $probePath "$targetPrefix/$(Split-Path -Leaf $probePath)" `
            2>&1 | Out-Null
        $copyExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($copyExitCode -ne 0) {
        throw "Could not stage serial probe (exit $copyExitCode)."
    }
}

Write-Host "Running $Mode CH341 serial unbind/rebind test"
$result = Invoke-PrivateRemoteScript -Script $outer
if (-not [string]::IsNullOrWhiteSpace($result.text)) {
    Write-Output $result.text
}
$captureId = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$artifactDirectory = Join-Path $repositoryRoot `
    "artifacts\navigation\raw\$captureId-d1-serial-rebind"
[IO.Directory]::CreateDirectory($artifactDirectory) | Out-Null
$artifactPath = Join-Path $artifactDirectory "$Mode.txt"
[IO.File]::WriteAllText(
    $artifactPath,
    $result.text + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false))
Write-Host "Raw serial evidence: $artifactPath"

Write-Host 'Restoring conservative safe-base after serial test'
& (Join-Path $PSScriptRoot 'test_navigation_non_motion_fault.ps1') `
    -Scenario chassis -CarIp $CarIp -ContainerName $ContainerName `
    -ConsoleConfigPath $ConsoleConfigPath -MaxLinear 0.05 `
    -MaxAngular 0.20 -RestoreOnly
if ($result.code -ne 0) {
    throw "Serial $Mode test failed with exit code $($result.code)."
}
Write-Host "Serial $Mode test passed with automatic rebind/recovery."

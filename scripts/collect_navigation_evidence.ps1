[CmdletBinding()]
param(
    [ValidateSet('snapshot', 'd1', 'd2', 'd3', 'd4')]
    [string]$Gate = 'snapshot',
    [string]$CarIp = '',
    [string]$SshUser = 'jetson',
    [string]$ContainerName = 'smartcar_icar_console',
    [string]$OutputRoot = '',
    [string]$StopTimingInput = '',
    [switch]$UseConsoleConfig,
    [string]$ConsoleConfigPath = '',
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sshExecutable = 'ssh'
$sshBaseArguments = @('-o', 'ConnectTimeout=10')
$sshDisplayArguments = @($sshBaseArguments)
if ($UseConsoleConfig) {
    if ([string]::IsNullOrWhiteSpace($ConsoleConfigPath)) {
        $ConsoleConfigPath = Join-Path $repositoryRoot 'smart-car-console\local-config.json'
    }
    if (-not (Test-Path -LiteralPath $ConsoleConfigPath -PathType Leaf)) {
        throw "Private console config was not found: $ConsoleConfigPath"
    }
    $privateConfig = Get-Content -LiteralPath $ConsoleConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($CarIp)) {
        $CarIp = [string]$privateConfig.car.host
    }
    $plinkPath = [string]$privateConfig.car.plinkPath
    $password = [string]$privateConfig.car.sshPassword
    $hostKey = [string]$privateConfig.car.sshHostKey
    if (-not [string]::IsNullOrWhiteSpace([string]$privateConfig.car.sshUser)) {
        $SshUser = [string]$privateConfig.car.sshUser
    }
    if ([string]::IsNullOrWhiteSpace($plinkPath) -or -not (Test-Path -LiteralPath $plinkPath -PathType Leaf)) {
        throw 'Configured plink executable was not found.'
    }
    if ([string]::IsNullOrWhiteSpace($password) -or [string]::IsNullOrWhiteSpace($hostKey)) {
        throw 'Console config must contain a non-empty SSH password and host key.'
    }
    $sshExecutable = $plinkPath
    $sshBaseArguments = @('-ssh', '-batch', '-hostkey', $hostKey, '-pw', $password)
    $sshDisplayArguments = @('-ssh', '-batch', '-hostkey', '[REDACTED]', '-pw', '[REDACTED]')
}

if ([string]::IsNullOrWhiteSpace($CarIp)) {
    throw 'CarIp must be supplied explicitly or through -UseConsoleConfig.'
}

if ($CarIp -notmatch '^[A-Za-z0-9.-]+$') { throw 'CarIp contains unsupported characters.' }
if ($SshUser -notmatch '^[A-Za-z0-9._-]+$') { throw 'SshUser contains unsupported characters.' }
if ($ContainerName -notmatch '^[A-Za-z0-9._-]+$') { throw 'ContainerName contains unsupported characters.' }

if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $repositoryRoot 'artifacts\navigation\raw'
}
$captureId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$captureDirectory = Join-Path $OutputRoot "$captureId-$Gate"
$target = "$SshUser@$CarIp"

function Remove-SensitiveText {
    param([string]$Text)
    $result = [string]$Text
    $result = [regex]::Replace($result, '(?im)(password|passwd|token|secret)\s*[:=]\s*\S+', '$1=[REDACTED]')
    $result = [regex]::Replace($result, '(?im)ssh-rsa\s+\S+', 'ssh-rsa [REDACTED]')
    return $result
}

function Invoke-ReadOnlyRemoteCapture {
    param([Parameter(Mandatory)][string]$Script)
    if ($Script -match '(?im)\bros2\s+(topic\s+pub|action\s+send_goal|service\s+call)\b') {
        throw 'Evidence collection rejected a motion-capable ROS command.'
    }
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $arguments = @($sshBaseArguments) + @($target, $remoteCommand)
    if ($DryRun) {
        $display = (($sshDisplayArguments + @($target, '<read-only evidence script>')) -join ' ')
        return "DRY RUN: $sshExecutable $display"
    }
    $output = & $sshExecutable @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $text = Remove-SensitiveText (($output | ForEach-Object { [string]$_ }) -join [Environment]::NewLine)
    if ($exitCode -ne 0) {
        throw "Read-only evidence collection failed with exit code $exitCode.`n$text"
    }
    return $text
}

$probePath = Join-Path $PSScriptRoot 'ros_readonly_probe.py'
if (-not (Test-Path -LiteralPath $probePath -PathType Leaf)) {
    throw "Read-only ROS probe is missing: $probePath"
}
$probeSource = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8
if ($probeSource -match '(?i)create_publisher|create_client|ActionClient|publish\s*\(') {
    throw 'Read-only ROS probe contains an output-capable API.'
}
$probeEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probeSource))

$remoteScript = @"
set -eu
cid=`$(docker ps -q --filter 'name=$ContainerName' | head -n 1)
if [ -z "`$cid" ]; then
  echo 'ROS container is not running: $ContainerName' >&2
  exit 20
fi

docker exec "`$cid" bash -lc '
  set -e
  source /opt/ros/foxy/setup.bash
  source /root/icar_ros2_ws/icar_ws/install/setup.bash
  source /root/icar_ros2_ws/software/library_ws/install/setup.bash
  test -f /root/ros2_navigation_overlay/install/setup.bash
  source /root/ros2_navigation_overlay/install/setup.bash
  export ROS_LOCALHOST_ONLY=1
  export FASTRTPS_DEFAULT_PROFILES_FILE=/root/ros2_navigation_overlay/install/share/icar_navigation/config/fastdds_localhost.xml
  export PYTHONUNBUFFERED=1

  printf "===== environment =====\\n"
  printf "ROS_DISTRO=%s\\n" "`$ROS_DISTRO"
  printf "RELEASE_ID=%s\\n" "`$(cat /root/ros2_navigation_overlay/.ready 2>/dev/null || echo unknown)"
  printf "ICAR_NAVIGATION_PREFIX=%s\\n" "`$(ros2 pkg prefix icar_navigation)"

  printf "===== Alarm interface =====\\n"
  ros2 interface show car_interfaces/msg/Alarm
  printf "===== NavigateToPose interface =====\\n"
  ros2 interface show nav2_msgs/action/NavigateToPose
  printf "===== bounded read-only graph probe =====\\n"
  printf "%s" "$probeEncoded" | base64 -d | timeout --signal=KILL 20 python3 -
'
"@

$evidenceText = Invoke-ReadOnlyRemoteCapture -Script $remoteScript
if ($DryRun) {
    Write-Host $evidenceText
    Write-Host 'Dry run complete; no network connection or evidence write occurred.'
    return
}

New-Item -ItemType Directory -Path $captureDirectory -Force | Out-Null
$snapshotPath = Join-Path $captureDirectory 'ros-read-only-snapshot.txt'
Set-Content -LiteralPath $snapshotPath -Value $evidenceText -Encoding UTF8

$artifacts = @('ros-read-only-snapshot.txt')
$stopTiming = $null
if (-not [string]::IsNullOrWhiteSpace($StopTimingInput)) {
    $timingText = Get-Content -LiteralPath $StopTimingInput -Raw
    $timing = $timingText | ConvertFrom-Json
    $triggeredAt = [DateTimeOffset]::Parse([string]$timing.triggeredAt)
    $zeroAt = [DateTimeOffset]::Parse([string]$timing.zeroAt)
    $latencyMs = ($zeroAt - $triggeredAt).TotalMilliseconds
    if ($latencyMs -lt 0 -or $latencyMs -gt 60000) {
        throw 'Stop timing input has an invalid latency.'
    }
    $stopTiming = [ordered]@{
        scenario = [string]$timing.scenario
        triggeredAt = $triggeredAt.ToUniversalTime().ToString('o')
        zeroAt = $zeroAt.ToUniversalTime().ToString('o')
        latencyMs = [Math]::Round($latencyMs, 3)
        source = 'operator-supplied timing evidence'
    }
    $timingPath = Join-Path $captureDirectory 'stop-timing.json'
    Set-Content -LiteralPath $timingPath -Value ($stopTiming | ConvertTo-Json -Depth 4) -Encoding UTF8
    $artifacts += 'stop-timing.json'
}

$record = [ordered]@{
    schema = 'AcceptanceEvidence/v1'
    captureId = $captureId
    gate = $Gate
    status = 'NOT_EVALUATED'
    collectedAt = (Get-Date).ToUniversalTime().ToString('o')
    target = [ordered]@{
        host = $CarIp
        sshUser = $SshUser
        container = $ContainerName
    }
    safety = [ordered]@{
        readOnly = $true
        motionCommandsSent = $false
        rosbagCaptured = $false
        credentialsIncluded = $false
    }
    artifacts = $artifacts
    stopTiming = $stopTiming
    note = 'Collection does not declare a gate PASS; review and timed acceptance evidence are still required.'
}
$recordPath = Join-Path $captureDirectory 'acceptance-evidence.json'
Set-Content -LiteralPath $recordPath -Value ($record | ConvertTo-Json -Depth 6) -Encoding UTF8

Write-Host "Read-only evidence captured at $captureDirectory"

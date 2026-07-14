[CmdletBinding()]
param(
    [string]$CarIp = '',
    [string]$SshUser = 'jetson',
    [string]$ContainerName = 'smartcar_icar_console',
    [string]$RemoteRoot = '/home/jetson/ros2_navigation_overlay',
    [switch]$UseConsoleConfig,
    [string]$ConsoleConfigPath = '',
    [switch]$SkipTests,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$sshExecutable = 'ssh'
$scpExecutable = 'scp'
$sshBaseArguments = @('-o', 'ConnectTimeout=10')
$sshDisplayBaseArguments = @($sshBaseArguments)
$scpBaseArguments = @()
$scpDisplayBaseArguments = @()

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
    $pscpPath = Join-Path (Split-Path -Parent $plinkPath) 'pscp.exe'
    if (-not (Test-Path -LiteralPath $pscpPath -PathType Leaf)) {
        throw 'pscp.exe must be installed beside the configured plink executable.'
    }
    $sshExecutable = $plinkPath
    $scpExecutable = $pscpPath
    $sshBaseArguments = @('-ssh', '-batch', '-hostkey', $hostKey, '-pw', $password)
    $sshDisplayBaseArguments = @('-ssh', '-batch', '-hostkey', '[REDACTED]', '-pw', '[REDACTED]')
    $scpBaseArguments = @('-batch', '-hostkey', $hostKey, '-pw', $password)
    $scpDisplayBaseArguments = @('-batch', '-hostkey', '[REDACTED]', '-pw', '[REDACTED]')
}

if ([string]::IsNullOrWhiteSpace($CarIp)) {
    throw 'CarIp must be supplied explicitly or through -UseConsoleConfig.'
}

if ($CarIp -notmatch '^[A-Za-z0-9.-]+$') { throw 'CarIp contains unsupported characters.' }
if ($SshUser -notmatch '^[A-Za-z0-9._-]+$') { throw 'SshUser contains unsupported characters.' }
if ($ContainerName -notmatch '^[A-Za-z0-9._-]+$') { throw 'ContainerName contains unsupported characters.' }
if ($RemoteRoot -notmatch '^/[A-Za-z0-9._/-]+$') { throw 'RemoteRoot must be an absolute POSIX path.' }

$sourceRoot = Join-Path $repositoryRoot 'ros2_car_remote_ws\src'
$packages = @('car_interfaces', 'icar_base_node', 'icar_bringup', 'icar_navigation')
foreach ($package in $packages) {
    $packagePath = Join-Path $sourceRoot $package
    if (-not (Test-Path -LiteralPath $packagePath -PathType Container)) {
        throw "Required package is missing: $packagePath"
    }
}

$releaseId = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$remoteRelease = "$RemoteRoot/releases/$releaseId"
$containerStage = "/root/ros2_navigation_staging/$releaseId"
$target = "$SshUser@$CarIp"

function Format-Argument {
    param([string]$Value)
    if ($Value -match '^[A-Za-z0-9_./:@=-]+$') { return $Value }
    return "'" + $Value.Replace("'", "''") + "'"
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$ArgumentList,
        [string[]]$DisplayArgumentList = $ArgumentList
    )
    $display = (($DisplayArgumentList | ForEach-Object { Format-Argument $_ }) -join ' ')
    Write-Host "> $FilePath $display"
    if ($DryRun) { return }
    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

function Invoke-RemoteScript {
    param([Parameter(Mandatory)][string]$Script)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Script))
    $remoteCommand = "printf '%s' '$encoded' | base64 -d | bash"
    $arguments = @($sshBaseArguments) + @(
        $target,
        $remoteCommand
    )
    $displayArguments = @($sshDisplayBaseArguments) + @(
        $target,
        $remoteCommand
    )
    Invoke-NativeCommand -FilePath $sshExecutable -ArgumentList $arguments -DisplayArgumentList $displayArguments
}

Write-Host "Preparing immutable release $releaseId for $target"
Invoke-RemoteScript -Script @"
set -euo pipefail
mkdir -p '$remoteRelease/src'
"@

foreach ($package in $packages) {
    $arguments = @($scpBaseArguments) + @(
        '-q',
        '-r',
        (Join-Path $sourceRoot $package),
        "${target}:$remoteRelease/src/"
    )
    $displayArguments = @($scpDisplayBaseArguments) + @(
        '-q',
        '-r',
        (Join-Path $sourceRoot $package),
        "${target}:$remoteRelease/src/"
    )
    Invoke-NativeCommand -FilePath $scpExecutable -ArgumentList $arguments -DisplayArgumentList $displayArguments
}

$testCommands = if ($SkipTests) {
    'echo "Tests skipped by explicit -SkipTests option"'
} else {
    @"
colcon test --merge-install --packages-select car_interfaces icar_base_node icar_bringup icar_navigation --event-handlers console_cohesion+
colcon test-result --verbose
"@
}

Invoke-RemoteScript -Script @"
set -euo pipefail
cid=`$(docker ps -q --filter 'name=$ContainerName' | head -n 1)
if [ -z "`$cid" ]; then
  echo 'Required ROS container is not running: $ContainerName' >&2
  exit 20
fi

docker exec "`$cid" mkdir -p '$containerStage/src'
find '$remoteRelease/src' -type f -name '*.pyc' -delete
docker cp '$remoteRelease/src/.' "`$cid:$containerStage/src/"
docker exec "`$cid" bash -lc '
  set -eo pipefail
  source /opt/ros/foxy/setup.bash
  source /root/icar_ros2_ws/icar_ws/install/setup.bash
  source /root/icar_ros2_ws/software/library_ws/install/setup.bash
  cd $containerStage
  colcon build --merge-install --packages-select car_interfaces icar_base_node icar_bringup icar_navigation --event-handlers console_cohesion+
  $testCommands
  test -f install/setup.bash
' 2>&1 | tee '$remoteRelease/build.log'

mkdir -p '$remoteRelease'
docker cp "`$cid:$containerStage/install" '$remoteRelease/install'
test -f '$remoteRelease/install/setup.bash'
ln -sfn 'releases/$releaseId/install' '$RemoteRoot/install.next'
mv -Tf '$RemoteRoot/install.next' '$RemoteRoot/install'
printf '%s\n' '$releaseId' > '$RemoteRoot/.ready'

if ! docker inspect "`$cid" --format '{{range .Mounts}}{{println .Destination}}{{end}}' \
    | grep -Fxq '/root/ros2_navigation_overlay'; then
  docker exec "`$cid" mkdir -p '/root/ros2_navigation_overlay/releases/$releaseId'
  docker cp '$remoteRelease/install' "`$cid:/root/ros2_navigation_overlay/releases/$releaseId/install"
  docker exec "`$cid" ln -sfn 'releases/$releaseId/install' '/root/ros2_navigation_overlay/install.next'
  docker exec "`$cid" mv -Tf '/root/ros2_navigation_overlay/install.next' '/root/ros2_navigation_overlay/install'
  docker exec "`$cid" bash -lc "printf '%s\\n' '$releaseId' > /root/ros2_navigation_overlay/.ready"
fi

printf 'RELEASE_ID=%s\nOVERLAY=%s\n' '$releaseId' '$RemoteRoot/install/setup.bash'
"@

if ($DryRun) {
    Write-Host 'Dry run complete; no files were copied and no remote commands were executed.'
} else {
    Write-Host "Release $releaseId built and promoted. Runtime nodes were not started or restarted."
}

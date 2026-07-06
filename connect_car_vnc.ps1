param(
  [Parameter(Mandatory = $true)]
  [string]$CarIp
)

$viewer = "C:\Program Files\TigerVNC\vncviewer.exe"

if (-not (Test-Path -LiteralPath $viewer)) {
  throw "TigerVNC Viewer not found at $viewer"
}

Write-Host "Opening VNC connection to $CarIp ..."
Write-Host "When prompted, use the car VNC password from your manual or lab handover notes."
Start-Process -FilePath $viewer -ArgumentList @($CarIp)

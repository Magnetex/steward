# Serve Build Steward to other devices on your Wi-Fi (phone, tablet).
#
# Binds to 0.0.0.0 so the LAN can reach it. Debug mode is deliberately OFF:
# the Werkzeug debugger is a remote-code-execution hole once the server is
# listening on anything other than localhost.
#
# Usage:  .\tools\serve-lan.ps1  [-Port 5055]

param([int]$Port = 5055)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "No venv at .venv - run the Setup steps in README.md first." }

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    ForEach-Object { $_.IPAddress }

Write-Host ""
Write-Host "  Open one of these on your phone (same Wi-Fi):" -ForegroundColor Cyan
foreach ($ip in $ips) { Write-Host "      http://${ip}:${Port}" -ForegroundColor Green }
Write-Host ""
$wifi = Get-NetConnectionProfile | Where-Object { $_.InterfaceAlias -eq "Wi-Fi" }
if ($wifi -and $wifi.NetworkCategory -eq "Public") {
    Write-Host "  ! Your Wi-Fi is on the PUBLIC firewall profile - inbound is blocked." -ForegroundColor Yellow
    Write-Host "    On your own home network, set it to Private (ADMIN PowerShell):" -ForegroundColor DarkGray
    Write-Host "      Set-NetConnectionProfile -InterfaceAlias 'Wi-Fi' -NetworkCategory Private" -ForegroundColor DarkGray
    Write-Host ""
}
Write-Host "  Nothing loads? Allow the port once, in an ADMIN PowerShell:" -ForegroundColor DarkGray
Write-Host "      New-NetFirewallRule -DisplayName 'Build Steward' -Direction Inbound ``" -ForegroundColor DarkGray
Write-Host "          -Protocol TCP -LocalPort $Port -Action Allow -Profile Private" -ForegroundColor DarkGray
Write-Host ""

$env:FLASK_APP = "wsgi.py"
& $python -m flask --app wsgi run --host 0.0.0.0 --port $Port

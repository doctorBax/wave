# Stop Wave DPI and restore the previous system proxy before removing files.
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'WaveDPI'
$runner = Join-Path $root 'wave-dpi.cmd'
if (Test-Path $runner) { & $runner stop }
Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'WaveDPI' -ErrorAction SilentlyContinue
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
[Environment]::SetEnvironmentVariable('Path', (($userPath -split ';' | Where-Object { $_ -and $_ -ne $root }) -join ';'), 'User')
Remove-Item -Path $root -Recurse -Force
Write-Host 'Wave DPI removed.'

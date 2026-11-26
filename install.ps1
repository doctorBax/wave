# Wave DPI Windows installer. Run as a regular user after the repo becomes public:
# irm https://raw.githubusercontent.com/doctorBax/wave/main/install.ps1 | iex
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'WaveDPI'
$temp = Join-Path $env:TEMP ([System.IO.Path]::GetRandomFileName())
$zip = Join-Path $temp 'wave.zip'
$source = Join-Path $temp 'sources'
New-Item -ItemType Directory -Force -Path $temp, $source | Out-Null
try {
    try {
        Invoke-WebRequest -Uri 'https://github.com/doctorBax/wave/archive/refs/heads/main.zip' -OutFile $zip -UseBasicParsing
    } catch {
        throw "Could not download Wave DPI. Make the GitHub repository public first. Details: $_"
    }
    Expand-Archive -Path $zip -DestinationPath $source -Force
    $checkout = Get-ChildItem $source -Directory | Select-Object -First 1
    if (-not $checkout) { throw 'Missing source directory in archive' }
    $py = $null
    foreach ($binary in @('python', 'py')) {
        if (Get-Command $binary -ErrorAction SilentlyContinue) {
            try {
                $candidate = & $binary -c 'import sys; print(sys.executable)' 2>$null
                if ($LASTEXITCODE -eq 0 -and (Test-Path $candidate)) { $py = $candidate; break }
            } catch {}
        }
    }
    if (-not $py) {
        $embed = Join-Path $root 'python'
        New-Item -ItemType Directory -Force -Path $embed | Out-Null
        Write-Host 'Python not found: downloading official embedded Python 3.12...'
        $pyzip = Join-Path $temp 'python.zip'
        Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $pyzip -UseBasicParsing
        Expand-Archive -Path $pyzip -DestinationPath $embed -Force
        $py = Join-Path $embed 'python.exe'
    }
    if (-not (Test-Path $py)) { throw 'Python executable not found' }
    $existing = Join-Path $root 'wave-dpi.cmd'
    if (Test-Path $existing) { & $existing stop }
    New-Item -ItemType Directory -Force -Path (Join-Path $root 'wavedpi') | Out-Null
    Copy-Item (Join-Path $checkout.FullName 'launch.py') (Join-Path $root 'launch.py') -Force
    Copy-Item (Join-Path $checkout.FullName 'wavedpi\*.py') (Join-Path $root 'wavedpi') -Force
    $runner = Join-Path $root 'wave-dpi.cmd'
    $cmd = "@echo off`r`n`"$py`" `"$root\launch.py`" %*`r`n"
    [IO.File]::WriteAllText($runner, $cmd, [Text.Encoding]::ASCII)
    $uninstall = Join-Path $root 'uninstall.ps1'
    Copy-Item (Join-Path $checkout.FullName 'uninstall.ps1') $uninstall -Force
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $userPath) { $userPath = '' }
    if (($userPath -split ';') -notcontains $root) {
        [Environment]::SetEnvironmentVariable('Path', ($userPath.TrimEnd(';') + ';' + $root).TrimStart(';'), 'User')
    }
    $env:Path += ';' + $root
    Write-Host 'Wave DPI installed. Command: wave-dpi' -ForegroundColor Green
    Write-Host 'No administrator rights needed. Windows handles only apps using the system HTTP proxy.'
    & $runner
} finally {
    Remove-Item -Path $temp -Recurse -Force -ErrorAction SilentlyContinue
}

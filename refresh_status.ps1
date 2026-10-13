# Read-only ADB snapshot for the local file:// HTML page.
param(
    [string]$AdbPath,
    [string]$OutputPath = (Join-Path $PSScriptRoot 'board_status.js')
)

if (-not $AdbPath) {
    $candidates = @(
        (Join-Path $PSScriptRoot '..\Tools\platform-tools\adb.exe'),
        (Join-Path $PSScriptRoot '..\..\Tools\platform-tools\adb.exe')
    )
    $AdbPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $AdbPath) {
        $command = Get-Command adb -ErrorAction SilentlyContinue
        if ($command) { $AdbPath = $command.Source }
    }
}
if (-not $AdbPath -or -not (Test-Path -LiteralPath $AdbPath)) {
    throw '找不到 adb.exe；请传入 -AdbPath 的完整路径。'
}

$deviceLines = @(& $AdbPath devices)
if ($LASTEXITCODE -ne 0) { throw 'adb devices 执行失败。' }
$serials = @($deviceLines | ForEach-Object {
    if ($_ -match '^([^\s]+)\s+device\s*$') { $Matches[1] }
})
if ($serials.Count -ne 1) {
    throw "需要恰好 1 台已连接的 ADB 设备，当前为 $($serials.Count) 台。"
}
$serial = $serials[0]

$listener = @(& $AdbPath -s $serial shell "ss -lntp 'sport = :5000'" 2>$null) -join "`n"
if ($LASTEXITCODE -ne 0) { throw '读取 TCP 5000 监听状态失败。' }
$pidValue = $null
if ($listener -match 'pid=(\d+)') { $pidValue = [int]$Matches[1] }
$processCommand = ''
if ($pidValue) {
    $processCommand = (@(& $AdbPath -s $serial shell "ps -ww -p $pidValue -o args=" 2>$null) -join ' ').Trim()
    if ($LASTEXITCODE -ne 0) { $processCommand = '' }
}
$cameraUsers = @(& $AdbPath -s $serial shell 'lsof /dev/video44 2>/dev/null' 2>$null) -join "`n"
if ($LASTEXITCODE -ne 0) { $cameraUsers = '' }
$connections = @(& $AdbPath -s $serial shell "ss -ntp 'sport = :5000'" 2>$null) -join "`n"
if ($LASTEXITCODE -ne 0) { $connections = '' }
$addresses = @(& $AdbPath -s $serial shell 'hostname -I' 2>$null) -join ' '
$boardIp = ''
if ($addresses -match '\b192\.168\.2\.\d+\b') { $boardIp = $Matches[0] }
elseif ($addresses -match '\b(?:\d{1,3}\.){3}\d{1,3}\b') { $boardIp = $Matches[0] }

$cameraOwned = $false
if ($pidValue) { $cameraOwned = $cameraUsers -match "(?m)^\S+\s+$pidValue\s" }
$h265 = $processCommand -match '(?:^|\s)mpph265enc(?:\s|$)'
$preview = $processCommand -match '(?:^|\s)tee(?:\s|$)' -and
           $processCommand -match '(?:auto|xv|gl|wayland)videosink'
$connected = $connections -match '(?m)^ESTAB\s'

# Query the new controller without starting services or changing camera state.
$ffState = $null
$ffResponse = @(& $AdbPath -s $serial shell 'test -f /userdata/av_dev/ffmpeg_pipeline/avctl.py && python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py status' 2>$null) -join "`n"
if ($LASTEXITCODE -eq 0 -and $ffResponse.Trim()) {
    try {
        $parsed = $ffResponse.Trim() | ConvertFrom-Json
        if ($parsed.ok) { $ffState = $parsed.result }
    } catch { $ffState = $null }
}
$useFFmpeg = $ffState -and ($ffState.state -in @('running','starting','recovering') -or -not $pidValue)

$status = [ordered]@{
    sampledAt = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
    sampledAtEpochMs = [DateTimeOffset]::Now.ToUnixTimeMilliseconds()
    adbSerial = $serial
    boardIp = $boardIp
    camera = '/dev/video44'
    port = 5000
    listenerPid = $pidValue
    portListening = [bool]$pidValue
    cameraOwnedByListener = [bool]$cameraOwned
    h265Pipeline = [bool]$h265
    previewBranchConfigured = [bool]$preview
    tcpClientConnected = [bool]$connected
    pipelineType = 'gstreamer'
}
if ($useFFmpeg) {
    $rtspListener = @(& $AdbPath -s $serial shell "ss -lntp 'sport = :8554'" 2>$null) -join "`n"
    $rtspPid = $null
    if ($rtspListener -match 'pid=(\d+)') { $rtspPid = [int]$Matches[1] }
    $encoderOwnsCamera = $false
    if ($ffState.capturePid) { $encoderOwnsCamera = $cameraUsers -match "(?m)^\S+\s+$($ffState.capturePid)\s" }
    $rtspConnections = @(& $AdbPath -s $serial shell "ss -Hntp 'sport = :8554'" 2>$null)
    $remoteConnected = $false
    foreach ($line in $rtspConnections) {
        $columns = @($line.Trim() -split '\s+')
        if ($columns.Count -ge 5 -and $columns[0] -eq 'ESTAB' -and $columns[4] -notmatch '^(127\.|\[?::1\]?:|\[?::ffff:127\.)') { $remoteConnected = $true }
    }
    $status.pipelineType = 'ffmpeg'
    if ($ffState.config) { $status.camera = $ffState.config.device }
    $status.port = 8554
    $status.listenerPid = $rtspPid
    $status.portListening = [bool]$rtspPid
    $status.cameraOwnedByListener = [bool]$encoderOwnsCamera
    $status.h265Pipeline = $ffState.encoder -eq 'hevc_rkmpp' -and $ffState.state -eq 'running'
    $status.previewBranchConfigured = [bool]$ffState.previewRunning
    $status.tcpClientConnected = [bool]$remoteConnected
    $status['encoderPid'] = $ffState.capturePid
    $status['streamReady'] = [bool]$ffState.rtspReady
    $status['hardwareDeviceOpen'] = [bool]$ffState.vpuDeviceOpen
    $status['fps'] = $ffState.fps
    $status['frame'] = $ffState.frame
    $status['recording'] = [bool]$ffState.recording
    $status['recordingFile'] = $ffState.recordingFile
    $status['lastRecording'] = $ffState.lastRecording
    $status['readers'] = $ffState.readers
    $status['lastError'] = $ffState.lastError
}
$json = $status | ConvertTo-Json -Depth 12 -Compress
$targetDir = Split-Path -Parent $OutputPath
if ($targetDir -and -not (Test-Path -LiteralPath $targetDir)) {
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}
[System.IO.File]::WriteAllText($OutputPath, "window.EVM3588Status = $json;`n", (New-Object System.Text.UTF8Encoding($false)))
Write-Host "状态已写入：$OutputPath"
Write-Host "采样时间：$($status.sampledAt)；链路：$($status.pipelineType)；H.265 在线：$($status.h265Pipeline)；远程客户端：$($status.tcpClientConnected)"

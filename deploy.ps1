# Deploy project scripts to EVM3588-B from Windows PowerShell.
# Does not stop a running GStreamer pipeline. BuildExamples is optional.
param(
    [string]$AdbPath,
    [switch]$BuildExamples
)

$boardDir = Join-Path $PSScriptRoot 'board'
$destination = '/userdata/av_dev'
if (-not (Test-Path -LiteralPath $boardDir)) { throw "找不到代码目录：$boardDir" }
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

$devices = @(& $AdbPath devices)
if ($LASTEXITCODE -ne 0) { throw 'adb devices 执行失败。' }
$serials = @($devices | ForEach-Object {
    if ($_ -match '^([^\s]+)\s+device\s*$') { $Matches[1] }
})
if ($serials.Count -ne 1) {
    throw "需要恰好 1 台已连接的 ADB 设备，当前为 $($serials.Count) 台。"
}
$serial = $serials[0]

& $AdbPath -s $serial shell "mkdir -p $destination"
if ($LASTEXITCODE -ne 0) { throw '创建板端目录失败。' }
$scripts = @(Get-ChildItem -LiteralPath $boardDir -Filter '*.sh' -File | Sort-Object Name)
if ($scripts.Count -eq 0) { throw "没有找到 Shell 脚本：$boardDir" }
foreach ($script in $scripts) {
    & $AdbPath -s $serial push $script.FullName "$destination/"
    if ($LASTEXITCODE -ne 0) { throw "推送失败：$($script.Name)" }
}
$sourceDir = Join-Path $boardDir 'v4l2_mpp_enc'
if (Test-Path -LiteralPath $sourceDir) {
    & $AdbPath -s $serial shell "mkdir -p $destination/mpp_route2"
    if ($LASTEXITCODE -ne 0) { throw '创建路线二目录失败。' }
    $sources = @(Get-ChildItem -LiteralPath $sourceDir -File | Sort-Object Name)
    foreach ($source in $sources) {
        & $AdbPath -s $serial push $source.FullName "$destination/mpp_route2/"
        if ($LASTEXITCODE -ne 0) { throw "推送 C 源码失败：$($source.Name)" }
    }
}
& $AdbPath -s $serial shell "chmod +x $destination/*.sh"
if ($LASTEXITCODE -ne 0) { throw '设置板端脚本权限失败。' }
& $AdbPath -s $serial shell "test -f $destination/07_h265_preview_tcp.sh && ls -l $destination/07_h265_preview_tcp.sh"
if ($LASTEXITCODE -ne 0) { throw '板端新脚本验证失败。' }

if ($BuildExamples) {
    & $AdbPath -s $serial shell "cd $destination/mpp_route2 && make"
    if ($LASTEXITCODE -ne 0) { throw 'C 示例编译失败；请检查 MPP 开发头文件和 Makefile。' }
}

Write-Host "部署完成：$($scripts.Count) 个脚本已上传至 $destination；当前视频进程未被脚本停止。"
Write-Host '板端只读检查：cd /userdata/av_dev && bash 07_h265_preview_tcp.sh --check'
Write-Host '需要切换到新脚本时，先在原管线的终端按 Ctrl+C，再运行：'
Write-Host '  DISPLAY=:0 bash /userdata/av_dev/07_h265_preview_tcp.sh'

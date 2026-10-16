# Upload source only. Default: product controller and diagnostic scripts.
param(
    [string]$AdbPath,
    [switch]$IncludeExamples,
    [switch]$BuildExamples,
    [switch]$ListOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$destination = '/userdata/av_dev'
if ($BuildExamples) { $IncludeExamples = $true }
$plan = @()
$pipelineDir = Join-Path $projectRoot 'board\ffmpeg_pipeline'
foreach ($source in Get-ChildItem -LiteralPath $pipelineDir -Recurse -File) {
    $relative = $source.FullName.Substring($pipelineDir.Length + 1).Replace('\','/')
    if ($relative -match '^(runtime|build|state|logs|recordings|snapshots|__pycache__)/' -or $relative -match '/__pycache__/') { continue }
    if ($source.Extension -notin @('.py','.sh','.json','.yml','.patch','.h','.c') -or $source.Name -eq 'config.json') { continue }
    if ($relative -notmatch '^[A-Za-z0-9_./-]+$') { throw "不支持的板端路径：$relative" }
    $plan += [pscustomobject]@{ Local=$source.FullName; Remote="$destination/ffmpeg_pipeline/$relative" }
}
foreach ($source in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'board\diagnostics') -Filter '*.sh' -File) {
    $plan += [pscustomobject]@{ Local=$source.FullName; Remote="$destination/$($source.Name)" }
}
if ($IncludeExamples) {
    foreach ($source in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'examples\gstreamer') -Filter '*.sh' -File) {
        $plan += [pscustomobject]@{ Local=$source.FullName; Remote="$destination/$($source.Name)" }
    }
    foreach ($source in Get-ChildItem -LiteralPath (Join-Path $projectRoot 'examples\mpp_c_api') -File) {
        if ($source.Extension -in @('.c','.h') -or $source.Name -eq 'Makefile') {
            $plan += [pscustomobject]@{ Local=$source.FullName; Remote="$destination/mpp_route2/$($source.Name)" }
        }
    }
}
if ($ListOnly) { $plan | ConvertTo-Json -Depth 3; return }
if (-not $AdbPath) {
    $candidates = @((Join-Path $projectRoot '..\Tools\platform-tools\adb.exe'), (Join-Path $projectRoot '..\..\Tools\platform-tools\adb.exe'))
    $AdbPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $AdbPath) { $command = Get-Command adb -ErrorAction SilentlyContinue; if ($command) { $AdbPath = $command.Source } }
}
if (-not $AdbPath -or -not (Test-Path -LiteralPath $AdbPath)) { throw '找不到 adb.exe；请传入 -AdbPath 的完整路径。' }
$devices = @(& $AdbPath devices)
if ($LASTEXITCODE -ne 0) { throw 'adb devices 执行失败。' }
$serials = @($devices | ForEach-Object { if ($_ -match '^([^\s]+)\s+device\s*$') { $Matches[1] } })
if ($serials.Count -ne 1) { throw "需要恰好 1 台 ADB 设备，当前为 $($serials.Count) 台。" }
$serial = $serials[0]
foreach ($folder in ($plan.Remote | ForEach-Object { $_.Substring(0,$_.LastIndexOf('/')) } | Sort-Object -Unique)) {
    & $AdbPath -s $serial shell "mkdir -p $folder"
    if ($LASTEXITCODE -ne 0) { throw "创建目录失败：$folder" }
}
foreach ($entry in $plan) {
    & $AdbPath -s $serial push $entry.Local $entry.Remote
    if ($LASTEXITCODE -ne 0) { throw "上传失败：$($entry.Local)" }
}
& $AdbPath -s $serial shell "chmod +x $destination/*.sh $destination/ffmpeg_pipeline/*.sh"
if ($LASTEXITCODE -ne 0) { throw '设置板端脚本权限失败。' }
& $AdbPath -s $serial shell "test -f $destination/ffmpeg_pipeline/camera_control/controller.py"
if ($LASTEXITCODE -ne 0) { throw '控制模块上传不完整。' }
if ($BuildExamples) {
    & $AdbPath -s $serial shell "cd $destination/mpp_route2 && make"
    if ($LASTEXITCODE -ne 0) { throw 'MPP C 示例编译失败，请检查开发头文件和运行库。' }
}
Write-Host "已上传 $($plan.Count) 个文件，未停止或重启当前直播。"
Write-Host '板端只读检查：python3 /userdata/av_dev/ffmpeg_pipeline/avctl.py check'

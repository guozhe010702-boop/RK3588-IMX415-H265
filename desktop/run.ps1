param()
$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv-desktop\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '先按操作指南创建 .venv-desktop 并安装 requirements.lock.txt。' }
& $python (Join-Path $PSScriptRoot 'main.py')
exit $LASTEXITCODE

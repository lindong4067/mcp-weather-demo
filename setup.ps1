# 一键恢复开发环境（Windows / PowerShell）
# 自动创建/复用 .venv，精确锁定版本安装 + 校验 + 冒烟测试。
# 与 setup.sh（Linux/macOS/WSL）功能一致。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File .\setup.ps1
#   （或在 PowerShell 里：Set-ExecutionPolicy -Scope Process Bypass; .\setup.ps1）
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PyCmd = "python"
if (-not (Get-Command $PyCmd -ErrorAction SilentlyContinue)) {
    $PyCmd = "py"   # Python Launcher
}

$VenvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "== [0/4] 创建虚拟环境 .venv =="
    & $PyCmd -m venv (Join-Path $PSScriptRoot ".venv")
}

Write-Host "== [1/4] 安装依赖（.venv 内，requirements.txt 已精确锁定版本）=="
& $VenvPy -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")

Write-Host "== [2/4] 校验关键包版本 =="
& $VenvPy -c "import importlib.metadata as m; [print('  -', p, m.version(p)) for p in ['mcp','httpx','openai']]"

Write-Host "== [3/4] 冒烟测试（stdio 链路：连接 server + 调用工具）=="
& $VenvPy (Join-Path $PSScriptRoot "test_client.py")

Write-Host "== [4/4] 环境就绪 =="
Write-Host "常用命令（直接调用 .venv\Scripts\python.exe，或先 .\.venv\Scripts\Activate.ps1）："
Write-Host "  .venv\Scripts\python.exe server.py"
Write-Host "  .venv\Scripts\python.exe agent.py --demo `"今天天气怎么样？`""
Write-Host "  .venv\Scripts\python.exe deploy.py"

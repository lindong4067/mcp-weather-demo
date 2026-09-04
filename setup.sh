#!/usr/bin/env bash
# 一键恢复开发环境：自动创建/复用虚拟环境(.venv)，精确锁定版本安装 + 校验 + 冒烟测试。
# 适用于：沙箱被重置后 / 全新机器 git clone 之后，跑这一条命令即可恢复可运行状态。
# 兼容 PEP 668（Ubuntu/Debian 禁止系统级 pip）：依赖全部装在 .venv 内，不污染系统 Python。
#
# 用法：
#   bash setup.sh            # 使用 python3
#   PYTHON=python3.12 bash setup.sh   # 指定解释器
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
VENV=".venv"
VENV_PY="$VENV/bin/python"

if [ ! -x "$VENV_PY" ]; then
  echo "== [0/4] 创建虚拟环境 $VENV =="
  "$PYTHON" -m venv "$VENV"
fi

echo "== [1/4] 安装依赖（装进 .venv，requirements.txt 已精确锁定版本）=="
"$VENV_PY" -m pip install -r requirements.txt

echo "== [2/4] 校验关键包版本 =="
"$VENV_PY" -c "import importlib.metadata as m; [print('  -', p, m.version(p)) for p in ['mcp', 'httpx', 'openai']]"

echo "== [3/4] 冒烟测试（stdio 链路：连接 server + 调用工具）=="
"$VENV_PY" test_client.py

echo "== [4/4] 环境就绪 ✅ =="
echo "常用命令（直接调用 .venv/bin/python，或先 source .venv/bin/activate）："
echo "  $VENV_PY server.py                                  # 启动 stdio 服务"
echo "  $VENV_PY agent.py --demo \"今天天气怎么样？\"          # Agent 自动调工具演示"
echo "  $VENV_PY deploy.py                                  # streamable-http 远程部署"
echo "提示：VSCode 的 MCP 配置（.vscode/mcp.json）也指向 $VENV_PY"

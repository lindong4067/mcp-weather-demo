#!/usr/bin/env bash
# 一键恢复开发环境：精确锁定版本安装 + 校验 + 冒烟测试。
# 适用于：沙箱被重置后 / 全新机器 git clone 之后，跑这一条命令即可恢复可运行状态。
#
# 用法：
#   bash setup.sh            # 使用 python3
#   PYTHON=python3.12 bash setup.sh   # 指定解释器
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

echo "== [1/4] 安装依赖（requirements.txt 已精确锁定版本）=="
"$PYTHON" -m pip install -r requirements.txt

echo "== [2/4] 校验关键包版本 =="
"$PYTHON" - <<'PY'
import importlib.metadata as m
for p in ["mcp", "httpx", "openai"]:
    print(f"  - {p} {m.version(p)}")
PY

echo "== [3/4] 冒烟测试（stdio 链路：连接 server + 调用工具）=="
"$PYTHON" test_client.py

echo "== [4/4] 环境就绪 ✅ =="
echo "常用命令："
echo "  python server.py                                    # 启动 stdio 服务"
echo "  python agent.py --demo \"今天天气怎么样？\"           # Agent 自动调工具演示"
echo "  python deploy.py                                    # streamable-http 远程部署"

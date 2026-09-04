"""
MCP 测试客户端 —— 通过 stdio 启动 server.py，列出工具并依次调用，验证整个链路是否打通。

用法：
    python test_client.py
"""

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    # 以子进程方式启动 MCP Server（stdio 传输）
    # 用 sys.executable 拉起子进程：依赖装在哪个 Python（如 .venv）就用哪个，避免系统 Python 找不到 mcp
    server_params = StdioServerParameters(command=sys.executable, args=["server.py"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) 列出已注册工具
            tools = await session.list_tools()
            print("== Server 已注册的工具 ==")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description}")
            print()

            # 2) 依次调用工具
            cases = [
                ("get_current_location", {}, "不传参：查询当前位置"),
                ("get_weather", {}, "不传参：查当前所在位置天气"),
                ("get_weather", {"city": "上海"}, "传参：查上海天气"),
            ]
            for name, args, label in cases:
                print(f"== 调用 {name} —— {label} ==")
                result = await session.call_tool(name, args)
                for content in result.content:
                    if getattr(content, "type", None) == "text":
                        print(content.text)
                print()
                await asyncio.sleep(0.3)  # 避免触发免费接口限频


if __name__ == "__main__":
    asyncio.run(main())

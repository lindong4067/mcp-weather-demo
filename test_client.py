"""
MCP 测试客户端 —— 通过 stdio 启动 server.py，列出工具并依次调用，验证整个链路是否打通。
用法：
    python test_client.py            # 正常验证链路
    python test_client.py --debug    # DEBUG 模式：记录与 MCP 的全部交互细节（研究学习用）
"""
import argparse
import asyncio
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from debug import DebugRecorder, FrameLoggingReadStream, FrameLoggingWriteStream

async def main() -> None:
    parser = argparse.ArgumentParser(description="MCP 测试客户端（验证 Server 链路）")
    parser.add_argument("--debug", action="store_true",
                        help="DEBUG 模式：记录与 MCP 的全部交互细节（研究学习用）")
    parser.add_argument("--debug-dir", default="debug_logs", help="DEBUG 日志输出目录")
    args = parser.parse_args()
    recorder = DebugRecorder(log_dir=args.debug_dir, enabled=args.debug)
    try:
        # 以子进程方式启动 MCP Server（stdio 传输）
        # 用 sys.executable 拉起子进程：依赖装在哪个 Python（如 .venv）就用哪个，避免系统 Python 找不到 mcp
        server_params = StdioServerParameters(command=sys.executable, args=["server.py"])
        async with stdio_client(server_params) as (read, write):
            if recorder.enabled:
                read = FrameLoggingReadStream(read, recorder, direction="server→client")
                write = FrameLoggingWriteStream(write, recorder, direction="client→server")
            async with ClientSession(read, write) as session:
                recorder.mcp_request("initialize", {})
                t0 = time.monotonic()
                init_result = await session.initialize()
                recorder.mcp_response("initialize", init_result,
                                      dur_ms=(time.monotonic() - t0) * 1000)
                # 1) 列出已注册工具
                t0 = time.monotonic()
                recorder.mcp_request("tools/list", {})
                tools_resp = await session.list_tools()
                recorder.mcp_response("tools/list", tools_resp,
                                      dur_ms=(time.monotonic() - t0) * 1000)
                tools = tools_resp.tools
                print("== Server 已注册的工具 ==")
                for t in tools:
                    print(f"  - {t.name}: {t.description}")
                print()
                # 2) 依次调用工具
                cases = [
                    ("get_current_location", {}, "不传参：查询当前位置"),
                    ("get_weather", {}, "不传参：查当前所在位置天气"),
                    ("get_weather", {"city": "上海"}, "传参：查上海天气"),
                ]
                for name, args_dict, label in cases:
                    print(f"== 调用 {name} —— {label} ==")
                    t0 = time.monotonic()
                    recorder.mcp_request("tools/call", {"name": name, "arguments": args_dict})
                    result = await session.call_tool(name, args_dict)
                    recorder.mcp_response("tools/call", result,
                                          dur_ms=(time.monotonic() - t0) * 1000)
                    for content in result.content:
                        if getattr(content, "type", None) == "text":
                            print(content.text)
                    print()
                    await asyncio.sleep(0.3)  # 避免触发免费接口限频
                recorder.event("client.done", {"tool_calls": len(cases)})
                recorder.summary(tool_calls=len(cases))
    finally:
        if recorder.enabled:
            print(f"\n== DEBUG 记录完成 ==")
            print(f"  结构化日志: {recorder.jsonl_path}")
            print(f"  可读日志:   {recorder.log_path}")
        recorder.close()

if __name__ == "__main__":
    asyncio.run(main())

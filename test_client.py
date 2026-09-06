"""
MCP 测试客户端 —— 通过 stdio 启动 server.py，依次验证三类能力：
  1) Tools    ：列出工具并依次调用（get_current_location / get_weather / get_weather_forecast）
  2) Resources：列出静态资源与模板资源，并读取全部资源（weather://cities / wmo-codes /
                server-info / {city}/current / {city}/forecast）
  3) Prompts  ：列出提示词，并拉取渲染（weather-assistant / travel-weather-plan / weather-briefing）

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

                # ========== 1) Tools：列出并调用 ==========
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

                cases = [
                    ("get_current_location", {}, "不传参：查询当前位置"),
                    ("get_weather", {}, "不传参：查当前所在位置天气"),
                    ("get_weather", {"city": "上海"}, "传参：查上海天气"),
                    ("get_weather_forecast", {"city": "上海", "days": 3}, "传参：查上海未来 3 天预报"),
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

                # ========== 2) Resources：列出并读取 ==========
                t0 = time.monotonic()
                recorder.mcp_request("resources/list", {})
                resources_resp = await session.list_resources()
                recorder.mcp_response("resources/list", resources_resp,
                                      dur_ms=(time.monotonic() - t0) * 1000)
                print("== Server 已注册的静态资源 ==")
                for r in resources_resp.resources:
                    print(f"  - {r.uri}: {r.description}")
                print()

                t0 = time.monotonic()
                recorder.mcp_request("resources/templates/list", {})
                tmpl_resp = await session.list_resource_templates()
                recorder.mcp_response("resources/templates/list", tmpl_resp,
                                      dur_ms=(time.monotonic() - t0) * 1000)
                print("== Server 已注册的资源模板 ==")
                for t in tmpl_resp.resource_templates:
                    print(f"  - {t.uri_template}: {t.description}")
                print()

                read_cases = [
                    ("weather://cities", "静态资源：常用城市列表"),
                    ("weather://wmo-codes", "静态资源：WMO 天气代码对照表"),
                    ("weather://server-info", "静态资源：Server 能力说明"),
                    ("weather://上海/current", "模板资源：上海当前天气"),
                    ("weather://上海/forecast", "模板资源：上海未来 7 天预报"),
                ]
                for uri, label in read_cases:
                    print(f"== 读取资源 {uri} —— {label} ==")
                    t0 = time.monotonic()
                    recorder.mcp_request("resources/read", {"uri": uri})
                    result = await session.read_resource(uri)
                    recorder.mcp_response("resources/read", result,
                                          dur_ms=(time.monotonic() - t0) * 1000)
                    for content in result.contents:
                        text = getattr(content, "text", None)
                        if text is not None:
                            print(text)
                    print()
                    await asyncio.sleep(0.3)

                # ========== 3) Prompts：列出并拉取 ==========
                t0 = time.monotonic()
                recorder.mcp_request("prompts/list", {})
                prompts_resp = await session.list_prompts()
                recorder.mcp_response("prompts/list", prompts_resp,
                                      dur_ms=(time.monotonic() - t0) * 1000)
                print("== Server 已注册的提示词 ==")
                for p in prompts_resp.prompts:
                    args = ", ".join(
                        f"{a.name}{'' if a.required else '?'}" for a in (p.arguments or [])
                    )
                    print(f"  - {p.name}({args}): {p.description}")
                print()

                prompt_cases = [
                    ("weather-assistant", {}, "无参数：天气问答引导"),
                    # 注意：prompts/get 的 arguments 值为字符串（dict[str,str]），数字参数需传字符串
                    ("travel-weather-plan", {"city": "上海", "days": "3"}, "参数型：出行天气规划"),
                    ("weather-briefing", {}, "可选参数：每日天气简报（默认当前位置）"),
                    ("weather-briefing", {"city": "北京"}, "可选参数：每日天气简报（指定北京）"),
                ]
                for name, args_dict, label in prompt_cases:
                    print(f"== 获取提示词 {name} {args_dict or ''} —— {label} ==")
                    t0 = time.monotonic()
                    recorder.mcp_request("prompts/get", {"name": name, "arguments": args_dict})
                    result = await session.get_prompt(name, args_dict)
                    recorder.mcp_response("prompts/get", result,
                                          dur_ms=(time.monotonic() - t0) * 1000)
                    for msg in result.messages:
                        text = getattr(msg.content, "text", None) or ""
                        print(f"  [{msg.role}] {text[:120]}{'…' if len(text) > 120 else ''}")
                    print()

                recorder.event("client.done", {"tool_calls": len(cases),
                                               "resource_reads": len(read_cases),
                                               "prompt_gets": len(prompt_cases)})
                recorder.summary(tool_calls=len(cases), resource_reads=len(read_cases),
                                 prompt_gets=len(prompt_cases))
    finally:
        if recorder.enabled:
            print(f"\n== DEBUG 记录完成 ==")
            print(f"  结构化日志: {recorder.jsonl_path}")
            print(f"  可读日志:   {recorder.log_path}")
        recorder.close()


if __name__ == "__main__":
    asyncio.run(main())

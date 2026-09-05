#!/usr/bin/env python3
"""
MCP Agent —— 让 LLM 自动使用 MCP Server 暴露的工具。
场景：用户问"今天天气怎么样？"，Agent 会自动：
  1) 调用 get_current_location 获取当前位置
  2) 调用 get_weather(位置) 查询该位置天气
  3) 用自然语言把天气告诉用户
原理（MCP 工具调用循环）：
  Agent 通过 MCP 客户端连接 Server → 把工具名/描述/参数 schema 喂给 LLM →
  LLM 认为需要时返回"函数调用请求" → Agent 在 MCP 会话里执行该工具 →
  把返回结果回填给 LLM → LLM 继续直到给出最终回答。
用法：
  方式一：真实 LLM（需要 OpenAI 兼容的 API key，DeepSeek/OpenAI/Kimi/Qwen 均可）
    export LLM_API_KEY=sk-xxx
    export LLM_BASE_URL=https://api.deepseek.com/v1   # 可选，默认 DeepSeek
    export LLM_MODEL=deepseek-chat                    # 可选，默认 deepseek-chat
    python agent.py "今天天气怎么样？"
  方式二：--demo 确定性演示（无需 API key，演示"自动调工具"的完整链路）
    python agent.py --demo "今天天气怎么样？"
  DEBUG 模式（研究学习用，记录 Agent 与 LLM / MCP 的全部交互细节）：
    python agent.py --demo --debug "今天天气怎么样？"
    python agent.py --debug "今天天气怎么样？"
    或设置环境变量 MCP_DEBUG=1。日志输出到 debug_logs/，详见 debug.py。
"""
import argparse
import asyncio
import json
import os
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from dotenv import load_dotenv
from debug import DebugRecorder, FrameLoggingReadStream, FrameLoggingWriteStream

# 自动加载项目根目录的 .env（存放 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 等环境变量）
load_dotenv()
# 默认使用 DeepSeek（OpenAI 兼容接口），可通过环境变量换成其它厂商
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
SYSTEM_PROMPT = (
    "你是一个生活助手，可以调用工具获取实时信息。关于天气："
    "若用户没有指定城市，先调用 get_current_location 获取当前位置，"
    "再把该位置作为参数调用 get_weather 查询天气；"
    "若用户指定了城市（如\"上海\"），直接调用 get_weather(city=城市名)。"
    "不要编造数据，一切以工具返回结果为准，最后用自然语言回答用户。"
)
# ---------------- MCP 工具 -> OpenAI function calling schema ----------------
def to_openai_tool(tool) -> dict:
    """把 MCP 工具定义转成 OpenAI 兼容的 tools 参数。"""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.input_schema,
        },
    }
def assistant_message(msg) -> dict:
    """把 LLM 返回的 message 对象序列化成可继续对话的 dict（含 tool_calls）。"""
    d = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return d
# ---------------- 工具调用主循环 ----------------
async def run_agent(session: ClientSession, client, model: str, query: str, recorder=None) -> None:
    """MCP 工具调用主循环。recorder 为 DebugRecorder（未启用 DEBUG 时为空操作）。"""
    recorder = recorder or DebugRecorder(enabled=False)
    is_demo = isinstance(client, DemoClient)
    recorder.event("agent.start", {
        "query": query,
        "mode": "demo" if is_demo else "llm",
        "llm": model,
        "base_url": os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL) if not is_demo else None,
    })
    # 1) 加载 MCP 工具 -> 喂给 LLM
    t0 = time.monotonic()
    recorder.mcp_request("tools/list", {})
    tools_resp = await session.list_tools()
    recorder.mcp_response("tools/list", tools_resp, dur_ms=(time.monotonic() - t0) * 1000)
    tools = tools_resp.tools
    openai_tools = [to_openai_tool(t) for t in tools]
    print("== MCP 工具已加载给 Agent ==")
    for t in openai_tools:
        print(f"  - {t['function']['name']}: {t['function']['description']}")
    print()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]
    n_tool_calls = 0
    for _turn in range(12):  # 最多 12 轮工具调用，防止死循环
        # 2) Agent -> LLM：发送完整上下文（system / user / assistant tool_calls / tool 结果）
        recorder.llm_request(model, [dict(m) for m in messages], openai_tools)
        t0 = time.monotonic()
        try:
            resp = await client.chat.completions.create(
                model=model, messages=messages, tools=openai_tools, tool_choice="auto"
            )
        except Exception as exc:
            recorder.llm_error(exc, dur_ms=(time.monotonic() - t0) * 1000)
            raise
        recorder.llm_response(resp, dur_ms=(time.monotonic() - t0) * 1000)
        msg = resp.choices[0].message
        # 没有工具调用请求 → LLM 给出最终回答
        if not msg.tool_calls:
            print("\n[Agent 最终回答]")
            print(msg.content)
            recorder.event("agent.done", {"reason": "final_answer", "turns": _turn + 1,
                                          "tool_calls": n_tool_calls})
            recorder.summary(turns=_turn + 1, tool_calls=n_tool_calls)
            return
        messages.append(assistant_message(msg))
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"\n[Agent 调用工具] {name}({args})")
            # 3) Agent -> MCP：调用工具；MCP -> Agent：返回结果
            recorder.mcp_request("tools/call", {"name": name, "arguments": args})
            t0 = time.monotonic()
            try:
                result = await session.call_tool(name, args)
            except Exception as exc:
                recorder.mcp_error("tools/call", exc, dur_ms=(time.monotonic() - t0) * 1000)
                raise
            recorder.mcp_response("tools/call", result, dur_ms=(time.monotonic() - t0) * 1000)
            n_tool_calls += 1
            text = "\n".join(
                c.text for c in result.content if getattr(c, "type", None) == "text"
            )
            print(f"  -> 返回: {text}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
    print("（达到最大工具调用轮数，已停止）")
    recorder.event("agent.done", {"reason": "max_turns", "turns": 12, "tool_calls": n_tool_calls})
    recorder.summary(turns=12, tool_calls=n_tool_calls)
# ---------------- 无 API key 的确定性演示客户端 ----------------
# 模拟 LLM 的"决策"：第 1 轮要定位，第 2 轮用定位结果查天气，第 3 轮给出最终回答。
class _DemoFunction:
    def __init__(self, name: str, arguments: str):
        self.name, self.arguments = name, arguments
class _DemoToolCall:
    def __init__(self, call_id: str, name: str, arguments: str):
        self.id = call_id
        self.function = _DemoFunction(name, arguments)
class _DemoMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
class _DemoChoice:
    def __init__(self, message):
        self.message = message
class _DemoResponse:
    def __init__(self, message):
        self.choices = [_DemoChoice(message)]
class _DemoCompletions:
    def __init__(self, owner):
        self._owner = owner
    async def create(self, **kwargs):
        return await self._owner._decide(kwargs)
class _DemoChat:
    def __init__(self, owner):
        self.completions = _DemoCompletions(owner)
class DemoClient:
    """确定性客户端：模拟 LLM 决策，演示完整的工具调用链（无需 API key）。"""
    def __init__(self):
        self.chat = _DemoChat(self)
        self._turn = 0
    async def _decide(self, kwargs):
        self._turn += 1
        if self._turn == 1:
            return _DemoResponse(_DemoMessage(
                tool_calls=[_DemoToolCall("demo_1", "get_current_location", "{}")]
            ))
        if self._turn == 2:
            # 从上一步定位结果里解析出城市名，作为天气查询参数
            city = "当前位置"
            for m in kwargs.get("messages", []):
                if m.get("role") == "tool" and "当前定位" in m.get("content", ""):
                    city = m["content"].split("当前定位：")[1].split("·")[0].strip()
                    break
            return _DemoResponse(_DemoMessage(
                tool_calls=[_DemoToolCall("demo_2", "get_weather", json.dumps({"city": city}))]
            ))
        return _DemoResponse(_DemoMessage(
            content="好的！我根据你的当前位置查到了当地天气，完整数据见上方工具返回结果。"
        ))
# ---------------- 入口 ----------------
async def run() -> None:
    parser = argparse.ArgumentParser(description="使用 MCP 工具的天气 Agent")
    parser.add_argument("query", nargs="?", default="今天天气怎么样？", help="用户提问")
    parser.add_argument("--demo", action="store_true", help="无 API key 的确定性演示模式")
    parser.add_argument("--debug", action="store_true",
                        help="DEBUG 模式：记录 Agent 与 LLM / MCP 的全部交互细节（研究学习用）")
    parser.add_argument("--debug-dir", default="debug_logs",
                        help="DEBUG 日志输出目录（默认 debug_logs/）")
    args = parser.parse_args()
    debug_enabled = args.debug or os.getenv("MCP_DEBUG") == "1"
    recorder = DebugRecorder(log_dir=args.debug_dir, enabled=debug_enabled)
    try:
        # 用 sys.executable 拉起子进程：依赖装在哪个 Python（如 .venv）就用哪个，避免系统 Python 找不到 mcp
        server_params = StdioServerParameters(command=sys.executable, args=["server.py"])
        async with stdio_client(server_params) as (read, write):
            if recorder.enabled:
                # 包装 stdio 传输流：逐帧记录原始 JSON-RPC 消息（MCP 协议线格式）
                read = FrameLoggingReadStream(read, recorder, direction="server→client")
                write = FrameLoggingWriteStream(write, recorder, direction="client→server")
            async with ClientSession(read, write) as session:
                # MCP 握手：initialize（协议版本 / 能力 / Server 信息）
                recorder.mcp_request("initialize", {})
                t0 = time.monotonic()
                init_result = await session.initialize()
                recorder.mcp_response("initialize", init_result,
                                      dur_ms=(time.monotonic() - t0) * 1000)
                if args.demo:
                    client, model = DemoClient(), "demo"
                    print("== 演示模式：无 API key，用确定性逻辑模拟 LLM 决策 ==\n")
                else:
                    api_key = os.getenv("LLM_API_KEY")
                    if not api_key:
                        print("未设置 LLM_API_KEY。你可以：")
                        print("  1) 设置环境变量后用真实 LLM 运行：export LLM_API_KEY=sk-xxx")
                        print("  2) 先看完整流程：python agent.py --demo \"今天天气怎么样？\"")
                        recorder.event("agent.abort", {"reason": "missing_LLM_API_KEY"})
                        return
                    from openai import AsyncOpenAI
                    client = AsyncOpenAI(
                        api_key=api_key,
                        base_url=os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL),
                    )
                    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
                await run_agent(session, client, model, args.query, recorder)
    finally:
        if recorder.enabled:
            print(f"\n== DEBUG 记录完成 ==")
            print(f"  结构化日志: {recorder.jsonl_path}")
            print(f"  可读日志:   {recorder.log_path}")
        recorder.close()
def main() -> None:
    asyncio.run(run())
if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
debug.py —— DEBUG 模式：完整记录 Agent ↔ LLM / Agent ↔ MCP 的全部交互细节（研究/学习用）。

覆盖三层交互：
  1) Agent → LLM   ：每次 chat.completions 请求的完整 payload（model / messages / tools / 参数）
  2) LLM   → Agent ：每次响应的完整对象（id / model / finish_reason / message / tool_calls / usage 等）
  3) Agent ↔ MCP   ：initialize / tools/list / tools/call 的请求参数与完整响应
                     （含 content / structuredContent / isError），
                     以及传输层上的完整 JSON-RPC 协议消息（client→server / server→client，
                     覆盖请求 / 响应 / 通知 / 错误），可用于学习 MCP 协议报文格式。

输出（默认 <项目根>/debug_logs/）：
  - debug_<时间戳>.jsonl ：机器可读的结构化日志，每行一个 JSON 对象（完整字段、可回放）
  - debug_<时间戳>.log   ：人类可读的对齐日志（按时间线浏览学习）
每条交互都带：序号 seq、时间戳 ts、相对启动耗时 elapsed_ms、类别 category、方向 direction。

用法：
    python agent.py --demo --debug "今天天气怎么样？"    # 演示模式 + DEBUG（无需 API key）
    python agent.py --debug "今天天气怎么样？"           # 真实 LLM + DEBUG
    python test_client.py --debug                      # 仅 MCP 链路 + DEBUG
    环境变量 MCP_DEBUG=1 等价于 --debug。
"""
from __future__ import annotations

import dataclasses
import datetime
import enum
import json
import os
import time
from typing import Any, Optional


# ---------------------------------------------------------------- 工具函数
def _safe_json(obj: Any) -> Any:
    """把任意对象（pydantic 模型 / dataclass / enum / bytes / 普通容器）转成可 JSON 序列化的结构。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_safe_json(v) for v in obj]
    # pydantic v2 模型
    if hasattr(obj, "model_dump"):
        try:
            return _safe_json(obj.model_dump(mode="json"))
        except Exception:
            pass
    # dataclass
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        try:
            return _safe_json(dataclasses.asdict(obj))
        except Exception:
            pass
    # enum
    if isinstance(obj, enum.Enum):
        return obj.value
    # bytes
    if isinstance(obj, (bytes, bytearray, memoryview)):
        b = bytes(obj)
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            return {"__bytes_hex__": b.hex()}
    # 最后的兜底：尝试直接序列化，失败则转字符串
    try:
        return json.loads(json.dumps(obj, default=str))
    except Exception:
        return str(obj)


def _parse_frame(data: Any) -> Any:
    """把 stdio 传输层收到的原始字节帧解析成 JSON（MCP 的 stdio 传输是换行分隔的 JSON-RPC）。"""
    raw = bytes(data) if not isinstance(data, (bytes, bytearray, memoryview)) else bytes(data)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return {"__raw_hex__": raw.hex()}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {"__empty_frame__": True}
    parsed = []
    for ln in lines:
        try:
            parsed.append(json.loads(ln))
        except Exception:
            parsed.append({"__raw_line__": ln})
    return parsed[0] if len(parsed) == 1 else parsed


def _pp(obj: Any, max_len: int = 3000) -> str:
    """人类可读日志用的缩进打印，超长截断（完整内容见 .jsonl）。"""
    s = json.dumps(obj, ensure_ascii=False, indent=2) if not isinstance(obj, str) else obj
    if len(s) > max_len:
        s = s[:max_len] + f"\n  …（已截断 {len(s) - max_len} 字符，完整内容见 .jsonl）"
    return s


def _now_iso() -> str:
    return datetime.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _msg_human(m: dict) -> str:
    """把一条对话消息压缩成一行人类可读文本。"""
    role = m.get("role", "?")
    content = (m.get("content") or "")
    content = content.replace("\n", " ")[:160] if content else "∅"
    extra = ""
    if role == "tool":
        extra = f" (tool_call_id={m.get('tool_call_id')})"
    tcs = m.get("tool_calls")
    if tcs:
        names = ", ".join(
            f"{t.get('function', {}).get('name', '?')}({t.get('function', {}).get('arguments', '')})"
            for t in tcs
        )
        extra += f" → tool_calls[{len(tcs)}]: {names}"
    return f"[{role}]{extra} {content}"


# ---------------------------------------------------------------- 记录器
class DebugRecorder:
    """DEBUG 记录器。enabled=False 时所有方法为空操作（不落盘、不打印）。"""

    def __init__(self, log_dir: str = "debug_logs", enabled: bool = True, console: bool = True):
        self.enabled = enabled
        self.console = console
        self.jsonl_path: Optional[str] = None
        self.log_path: Optional[str] = None
        self._jsonl = None
        self._log = None
        self._seq = 0
        self._started = time.monotonic()
        self._counts: dict[str, int] = {}
        if not enabled:
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(log_dir, exist_ok=True)
        self.jsonl_path = os.path.join(log_dir, f"debug_{ts}.jsonl")
        self.log_path = os.path.join(log_dir, f"debug_{ts}.log")
        self._jsonl = open(self.jsonl_path, "w", encoding="utf-8")
        self._log = open(self.log_path, "w", encoding="utf-8")
        self._write_human("=" * 70)
        self._write_human(f"DEBUG 记录开始  {_now_iso()}  输出目录: {log_dir}")

    # ----- 底层写入 -----
    def _write_human(self, text: str) -> None:
        if self._log is not None:
            self._log.write(text + "\n")

    def record(self, category: str, direction: str, payload: Any, human: Optional[str] = None) -> None:
        if not self.enabled:
            return
        self._seq += 1
        self._counts[category] = self._counts.get(category, 0) + 1
        entry = {
            "seq": self._seq,
            "ts": _now_iso(),
            "elapsed_ms": round((time.monotonic() - self._started) * 1000, 1),
            "category": category,
            "direction": direction,
            "payload": _safe_json(payload),
        }
        if self._jsonl is not None:
            self._jsonl.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._jsonl.flush()
        block = human if human is not None else _pp(entry["payload"])
        self._write_human("-" * 70)
        self._write_human(f"[#{entry['seq']} {entry['ts']} +{entry['elapsed_ms']:>10.1f}ms] {direction}")
        self._write_human(block)
        if self.console:
            head = f"[debug #{entry['seq']}] {direction} {category}"
            print(head)

    # ----- 语义级：事件 -----
    def event(self, name: str, payload: Any, human: Optional[str] = None) -> None:
        self.record("event", "event", {"name": name, **payload},
                    human or f"事件 {name}\n{_pp(payload)}")

    # ----- 语义级：LLM -----
    def llm_request(self, model: str, messages: list, tools: list, extra: Optional[dict] = None) -> None:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            **(extra or {}),
        }
        msg_lines = "\n".join(_msg_human(m) for m in messages)
        tool_names = ", ".join(t["function"]["name"] for t in tools) if tools else "（无工具）"
        human = (
            f"模型: {model}    工具[{len(tools)}]: {tool_names}\n"
            f"对话上下文（{len(messages)} 条）:\n{msg_lines}"
        )
        self.record("llm_request", "agent→llm", payload, human)

    def llm_response(self, resp: Any, dur_ms: Optional[float] = None) -> None:
        d = self._llm_response_to_dict(resp)
        if dur_ms is not None:
            d["_duration_ms"] = round(dur_ms, 1)
        self.record("llm_response", "llm→agent", d, self._llm_response_human(d))

    def llm_error(self, exc: BaseException, dur_ms: Optional[float] = None) -> None:
        payload = {"error_type": type(exc).__name__, "error": str(exc)}
        if dur_ms is not None:
            payload["_duration_ms"] = round(dur_ms, 1)
        self.record("llm_error", "llm→agent", payload,
                    f"LLM 调用失败: {type(exc).__name__}: {exc}")

    @staticmethod
    def _llm_message_to_dict(msg: Any) -> dict:
        d = {"role": getattr(msg, "role", "assistant"), "content": getattr(msg, "content", None) or ""}
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tcs
            ]
        return d

    @classmethod
    def _llm_response_to_dict(cls, resp: Any) -> dict:
        # 真实 OpenAI 兼容响应：pydantic 模型，完整导出
        if hasattr(resp, "model_dump"):
            try:
                return resp.model_dump(mode="json")
            except Exception:
                pass
        # 演示客户端等自定义对象：手动抽取
        choices = getattr(resp, "choices", None)
        if choices:
            first = choices[0]
            msg = getattr(first, "message", None)
            d: dict[str, Any] = {
                "choices": [
                    {
                        "index": getattr(first, "index", 0),
                        "finish_reason": getattr(first, "finish_reason", None),
                        "message": cls._llm_message_to_dict(msg) if msg is not None else None,
                    }
                ]
            }
            for attr in ("id", "model", "created"):
                if hasattr(resp, attr):
                    d[attr] = getattr(resp, attr)
            usage = getattr(resp, "usage", None)
            if usage is not None:
                d["usage"] = _safe_json(usage)
            return d
        return {"__raw__": str(resp)}

    @staticmethod
    def _llm_response_human(d: dict) -> str:
        lines = []
        if d.get("id"):
            lines.append(f"id={d['id']}  model={d.get('model')}  finish_reason={d.get('choices', [{}])[0].get('finish_reason')}")
        for i, ch in enumerate(d.get("choices", [])):
            msg = ch.get("message") or {}
            lines.append(f"choice[{i}] role={msg.get('role')} content={ (msg.get('content') or '∅').replace(chr(10), ' ')[:300] }")
            tcs = msg.get("tool_calls") or []
            for tc in tcs:
                fn = tc.get("function", {})
                lines.append(f"  tool_call[{tc.get('id')}] → {fn.get('name')}({fn.get('arguments')})")
        if d.get("usage"):
            u = d["usage"]
            lines.append("usage: prompt={} completion={} total={}".format(
                u.get("prompt_tokens"), u.get("completion_tokens"), u.get("total_tokens")))
        if d.get("_duration_ms") is not None:
            lines.append(f"耗时: {d['_duration_ms']} ms")
        return "\n".join(lines) or "(空响应)"

    # ----- 语义级：MCP -----
    def mcp_request(self, method: str, params: Any) -> None:
        self.record("mcp_request", "agent→mcp", {"method": method, "params": params},
                    f"MCP 请求 {method}\n参数: {_pp(params, 1500)}")

    def mcp_response(self, method: str, result: Any, dur_ms: Optional[float] = None) -> None:
        d = _safe_json(result)
        if dur_ms is not None:
            d["_duration_ms"] = round(dur_ms, 1)
        self.record("mcp_response", "mcp→agent", {"method": method, "result": d},
                    self._mcp_response_human(method, d))

    def mcp_error(self, method: str, exc: BaseException, dur_ms: Optional[float] = None) -> None:
        payload = {"method": method, "error_type": type(exc).__name__, "error": str(exc)}
        if dur_ms is not None:
            payload["_duration_ms"] = round(dur_ms, 1)
        self.record("mcp_error", "mcp→agent", payload,
                    f"MCP 调用失败 {method}: {type(exc).__name__}: {exc}")

    @staticmethod
    def _mcp_response_human(method: str, d: dict) -> str:
        result = d.get("result") or {}
        lines = [f"MCP 响应 {method}（{d.get('_duration_ms')} ms）" if d.get("_duration_ms") else f"MCP 响应 {method}"]
        if "isError" in result:
            lines.append(f"isError: {result['isError']}")
        content = result.get("content")
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            other = [c.get("type") for c in content if isinstance(c, dict) and c.get("type") != "text"]
            for t in texts:
                lines.append(f"  text: {t[:500]}{'…' if len(t) > 500 else ''}")
            if other:
                lines.append(f"  其他内容类型: {other}")
        sc = result.get("structuredContent")
        if sc is not None:
            lines.append(f"structuredContent: {_pp(sc, 1500)}")
        if not content and sc is None:
            lines.append("  (无内容)")
        return "\n".join(lines)

    # ----- 传输层：完整 JSON-RPC 协议消息 -----
    def frame(self, direction: str, data: Any) -> None:
        """记录一条 JSON-RPC 协议消息。

        流层传递的是 mcp SDK 的 SessionMessage（dataclass，内含 JSON-RPC 请求/响应/
        通知/错误对象），_safe_json 可完整序列化；个别场景下也可能是原始字节帧，
        此时退回按字节解析。
        """
        if not self.enabled:
            return
        if isinstance(data, (bytes, bytearray, memoryview)):
            parsed = _parse_frame(data)
            self.record("rpc_message", direction, parsed,
                        f"JSON-RPC 原始字节帧:\n{_pp(parsed, 2000)}")
        else:
            parsed = _safe_json(data)
            self.record("rpc_message", direction, parsed,
                        f"JSON-RPC 协议消息:\n{_pp(parsed, 2000)}")

    # ----- 汇总与关闭 -----
    def summary(self, **extra: Any) -> None:
        if not self.enabled:
            return
        payload = {
            "total_entries": self._seq,
            "counts_by_category": dict(self._counts),
            "total_elapsed_ms": round((time.monotonic() - self._started) * 1000, 1),
            **extra,
        }
        self.record("summary", "summary", payload,
                    "汇总\n" + _pp(payload))

    def close(self) -> None:
        if not self.enabled or self._jsonl is None:
            return
        self._write_human("=" * 70)
        self._write_human(f"DEBUG 记录结束  {_now_iso()}  共 {self._seq} 条交互")
        self._jsonl.close()
        self._log.close()
        self._jsonl = self._log = None


# ---------------------------------------------------------------- 传输层帧包装
class FrameLoggingReadStream:
    """包装 stdio 的读流（server→client），逐帧记录原始 JSON-RPC 消息。"""

    def __init__(self, inner, recorder: DebugRecorder, direction: str = "server→client"):
        self._inner = inner
        self._recorder = recorder
        self._direction = direction

    async def receive(self, max_bytes: int = 65536):
        data = await self._inner.receive(max_bytes)
        self._recorder.frame(self._direction, data)
        return data

    async def receive_nowait(self):
        data = await self._inner.receive_nowait()
        self._recorder.frame(self._direction, data)
        return data

    # 支持 async for 迭代（dispatcher 用 __aiter__ 消费读流）
    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            item = await self._inner.__anext__()
        except StopAsyncIteration:
            raise
        self._recorder.frame(self._direction, item)
        return item

    # 特殊方法不会被 __getattr__ 委托，需显式转发
    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        return await self._inner.__aexit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class FrameLoggingWriteStream:
    """包装 stdio 的写流（client→server），逐帧记录原始 JSON-RPC 消息。"""

    def __init__(self, inner, recorder: DebugRecorder, direction: str = "client→server"):
        self._inner = inner
        self._recorder = recorder
        self._direction = direction

    async def send(self, item):
        self._recorder.frame(self._direction, item)
        await self._inner.send(item)

    # 特殊方法不会被 __getattr__ 委托，需显式转发
    async def __aenter__(self):
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        return await self._inner.__aexit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._inner, name)

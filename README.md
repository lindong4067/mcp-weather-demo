# MCP Demo —— 当前位置 & 天气查询

一个用 Python 写的 MCP（Model Context Protocol）完整示例，包含 **Server**（暴露工具）与 **Agent**（LLM 自动调用工具）两部分：

| 工具 | 说明 |
|---|---|
| `get_current_location` | 查询当前位置（城市/省份/国家/经纬度/时区），基于出口 IP 定位 |
| `get_weather` | 查询天气；可传城市名（如"上海"），不传则用当前所在位置 |

所有数据源均为**免费、无需 API key** 的公开接口：
- 定位：`ipwho.is`（主）、`ipinfo.io`（备）
- 城市→经纬度：Open-Meteo Geocoding（支持中文城市名）
- 天气：Open-Meteo Forecast API

---

## 1. 项目结构

```
mcp_weather_demo/
├── server.py          # MCP Server（FastMCP，暴露两个工具）
├── agent.py           # MCP Agent（LLM 自动调用工具，支持 --demo 演示）
├── test_client.py     # 自带 stdio 测试客户端，一键验证链路
├── requirements.txt   # 依赖：mcp、httpx、openai
├── pyproject.toml     # 项目元信息（可选，支持 pip install -e .）
├── LICENSE            # MIT 许可
├── .gitignore
└── README.md
```

## 2. 安装依赖

```bash
cd mcp_weather_demo
pip install -r requirements.txt
```

## 3. 快速验证

```bash
python test_client.py
```

它会以子进程方式拉起 `server.py`，通过 stdio 完成初始化握手、列出工具并依次调用，输出类似：

```
== Server 已注册的工具 ==
  - get_current_location: ...
  - get_weather: ...

== 调用 get_current_location ==
当前定位：Beijing · Beijing · China
经纬度：(39.904201, 116.4069126)
时区：Asia/Shanghai

== 调用 get_weather —— 传参：查上海天气 ==
上海（中国） 当前天气：基本晴
温度：29.5°C（体感 32.3°C）...
```

## 4. 用真实客户端接入（三种方式）

### 方式 A：MCP Inspector（图形化调试，最快）
```bash
npx @modelcontextprotocol/inspector python server.py
```
浏览器打开 `http://localhost:6274`，点 **Connect** 后即可在 Tools 面板里看到并调用两个工具。

### 方式 B：Claude Desktop
编辑配置文件（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`；Windows：`%APPDATA%\Claude\claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "weather-location-demo": {
      "command": "python",
      "args": ["/绝对路径/mcp_weather_demo/server.py"]
    }
  }
}
```
重启 Claude Desktop，对话中直接问"帮我查一下上海的天气"，它就会调用你的 MCP 工具。

### 方式 C：Cursor
Settings → MCP → **Add new MCP server** → 选 `stdio`，command 填 `python /绝对路径/mcp_weather_demo/server.py`，启用后即可在对话里触发。

## 5. 原理一句话

MCP 的架构是 **Server 暴露工具 ↔ Client 发起调用**，中间走 JSON-RPC。本 demo 用官方 Python SDK 的 `FastMCP` 高阶封装：`@mcp.tool()` 装饰一个普通函数，它就变成了可被 AI 调用的工具；`mcp.run()` 默认以 **stdio** 传输运行（进程间通信），也支持换成 HTTP/SSE 走远程部署。

## 6. 让 Agent 自动使用这些工具

MCP 的价值在于：**Agent（LLM）能"看见"你的工具并自动决定调用**。流程是：

```
用户提问 → LLM 读取工具名/描述/参数schema → LLM 决定调用哪个工具
       → MCP 客户端执行工具 → 结果回填给 LLM → LLM 继续 → 最终回答
```

### 方式 A：现成客户端（零代码，推荐先试）
Claude Desktop / Cursor 等客户端配置好 MCP server 后，内置 Agent 会自动调工具。
配置方法见上文第 4 节。配好后直接问"今天天气怎么样？"，它会自动走"查位置 → 查天气"。

### 方式 B：自己写 Agent（`agent.py`）
本项目自带一个工具调用循环示例，完全按你的需求实现：**用户问"今天天气怎么样" → 先调 `get_current_location` 获取位置 → 再用该位置调 `get_weather` → 自然语言回答**。

先看完整流程（无需 API key，确定性演示）：
```bash
python agent.py --demo "今天天气怎么样？"
```

接真实 LLM（OpenAI 兼容接口，DeepSeek/OpenAI/Kimi/Qwen 均可）：
```bash
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1   # 可选，默认 DeepSeek
export LLM_MODEL=deepseek-chat                    # 可选，默认 deepseek-chat
python agent.py "今天天气怎么样？"
```

`agent.py` 里值得读的关键代码：
- `to_openai_tool()`：把 MCP 工具定义转换成 LLM 认识的 function-calling schema
- `run_agent()`：核心循环 —— 把工具喂给 LLM → LLM 返回 tool_calls → 在 MCP 会话执行 → 结果回填 → 直到 LLM 给出最终回答

## 7. 扩展方向

- 加 **Resource**：暴露静态数据（如"常用城市列表"）供客户端读取
- 加 **Prompt**：定义提示词模板，让客户端按模板引导 AI
- 换 **HTTP/SSE 传输**：`uvicorn server:app` 部署成远程服务
- 换成你自己的真实业务接口（数据库、内网 API），原理完全一致

## 注意事项

- IP 定位返回的是**出口 IP 所在城市**，可能不等于物理位置；在公司/代理环境下尤其如此。
- 免费接口有限频，demo 场景够用；生产请申请正式 API key 或换商业服务。

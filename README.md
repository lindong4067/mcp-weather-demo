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
├── server.py          # MCP Server（MCPServer，暴露两个工具）
├── agent.py           # MCP Agent（LLM 自动调用工具，支持 --demo 演示）
├── deploy.py          # streamable-http 远程部署入口（Web 常驻服务）
├── test_client.py     # 自带 stdio 测试客户端，一键验证链路
├── setup.sh           # 一键恢复环境（Linux/macOS/WSL）
├── setup.ps1          # 一键恢复环境（Windows/PowerShell）
├── requirements.txt   # 依赖（精确锁定版本：mcp==2.1.1 等）
├── pyproject.toml     # 项目元信息（可选，支持 pip install -e .）
├── LICENSE            # MIT 许可
├── .gitignore
└── README.md
```

## 2. 安装依赖
**推荐一键恢复**（沙箱被重置 / 全新 clone 后执行，装依赖+校验版本+冒烟测试一步到位）：
- **Windows / PowerShell**（依赖会装进项目内 `.venv`，不污染系统）：
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\setup.ps1
  ```
- **Linux / macOS / WSL**（同样自动建 `.venv`，兼容 PEP 668 禁止系统级 pip 的发行版）：
  ```bash
  bash setup.sh
  ```
或手动安装（Windows 用 venv 的 python 避免污染系统）：
```bash
cd mcp_weather_demo
# Windows:  .venv\Scripts\python.exe -m pip install -r requirements.txt
# Linux:    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
> 可复现性说明：沙箱的 Python 站点包可能被重置回基线版本，因此**一切以 GitHub 为准**——
> 代码全部推送、依赖精确锁定、CI 在全新环境自动验证。恢复开发环境只需 `git clone` + 上面的一键脚本。

## 3. 快速验证
依赖装在哪就用哪个 python 跑（`.venv` 里的 python 已装好全部依赖；系统 python 可能没有）：
```bash
# Windows:
.venv\Scripts\python.exe test_client.py
# Linux / macOS / WSL:
.venv/bin/python test_client.py
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
> 前置：Inspector 2.x 要求 **Node.js ≥ 22**。Windows 可用 `winget install OpenJS.NodeJS.LTS` 安装；装完 `node -v` 确认 ≥ v22。

在项目根目录启动（**务必用 `.venv` 里的 python 拉起 server**，系统 python 没有依赖）：
```bash
# Windows:
npx @modelcontextprotocol/inspector .venv\Scripts\python.exe server.py
# Linux / macOS / WSL:
npx @modelcontextprotocol/inspector .venv/bin/python server.py
```
浏览器打开 `http://localhost:6274`，点 **Connect** 后即可在 Tools 面板里看到并调用两个工具。

**关闭**：回到启动 Inspector 的终端，按 `Ctrl+C` 结束进程（直接关闭该终端窗口同样有效）。
> 提示：Inspector 只是调试工具，日常使用 VSCode/Claude Desktop 等客户端即可，无需常驻。

### 方式 B：Claude Desktop
编辑配置文件（macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`；Windows：`%APPDATA%\Claude\claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "weather-location-demo": {
      "command": "/绝对路径/mcp_weather_demo/.venv/bin/python",
      "args": ["/绝对路径/mcp_weather_demo/server.py"]
    }
  }
}
```
> `command` 要指向**项目 `.venv` 里的 python**（系统 python 没装依赖）：Windows 下是 `.venv\Scripts\python.exe`，Linux/macOS/WSL 下是 `.venv/bin/python`。重启 Claude Desktop，对话中直接问"帮我查一下上海的天气"，它就会调用你的 MCP 工具。

### 方式 C：Cursor
Settings → MCP → **Add new MCP server** → 选 `stdio`，command 填 `.venv` 里的 python + `server.py` 绝对路径：
- Windows：`C:\路径\mcp-weather-demo\.venv\Scripts\python.exe C:\路径\mcp-weather-demo\server.py`
- Linux/macOS/WSL：`/路径/mcp-weather-demo/.venv/bin/python /路径/mcp-weather-demo/server.py`
启用后即可在对话里触发。

### 方式 D：VSCode
在项目根目录建 `.vscode/mcp.json`（该文件已在 `.gitignore` 中，属本地环境配置，不随仓库提交）。`command` 用**项目 `.venv` 里的 python** 拉起 server：

**Windows**（普通方式打开文件夹即可）：
```json
{
  "servers": {
    "weather-location-demo": {
      "type": "stdio",
      "command": "C:\\路径\\mcp-weather-demo\\.venv\\Scripts\\python.exe",
      "args": ["C:\\路径\\mcp-weather-demo\\server.py"],
      "cwd": "C:\\路径\\mcp-weather-demo"
    }
  }
}
```
**WSL / Linux**（用 Remote-WSL 打开，server 在 WSL 内启动）：
```json
{
  "servers": {
    "weather-location-demo": {
      "type": "stdio",
      "command": "/路径/mcp-weather-demo/.venv/bin/python",
      "args": ["/路径/mcp-weather-demo/server.py"],
      "cwd": "/路径/mcp-weather-demo"
    }
  }
}
```
**使用前必须做这三步（少一步就可能"工具不生效、模型自己去查 API"）：**
1. **重载窗口**：命令面板（Ctrl+Shift+P）→ `Developer: Reload Window`。`.vscode/mcp.json` 是直接写进磁盘的，VSCode 只在启动/配置变更时读取，**不重载就不会发现 server**——这是最常见的坑。
2. **确认已连接且启用**：命令面板 → **MCP: List Servers**，确认 `weather-location-demo` 为 connected 且 enabled（若显示 disabled，选中它 → Enable）。
3. **确认工具已暴露给 Agent**：Chat 输入框下方点 **Configure Tools**，应能看到 `get_current_location`、`get_weather` 且开关打开。

配好后在对话里问"今天天气怎么样？"，它会自动走"查位置 → 查天气"。若模型偶尔没调用工具，在提问里点名即可，如"用 weather-location-demo 的两个工具查今天上海的天气"。

## 5. 原理一句话

MCP 的架构是 **Server 暴露工具 ↔ Client 发起调用**，中间走 JSON-RPC。本 demo 基于 **MCP Python SDK v2**，用官方高阶封装 `MCPServer`（v2 中由 v1 的 `FastMCP` 更名而来）：`@mcp.tool()` 装饰一个普通函数，它就变成了可被 AI 调用的工具；`mcp.run()` 默认以 **stdio** 传输运行（进程间通信），也支持换成 HTTP/SSE 走远程部署。

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

先看完整流程（无需 API key，确定性演示；Windows 用 `.venv\Scripts\python.exe`，Linux 用 `.venv/bin/python`）：
```bash
# Windows:
.venv\Scripts\python.exe agent.py --demo "今天天气怎么样？"
# Linux / macOS / WSL:
.venv/bin/python agent.py --demo "今天天气怎么样？"
```

接真实 LLM（OpenAI 兼容接口，DeepSeek/OpenAI/Kimi/Qwen 均可）：
```bash
# Linux/macOS/WSL：
export LLM_API_KEY=sk-xxx
export LLM_BASE_URL=https://api.deepseek.com/v1   # 可选，默认 DeepSeek
export LLM_MODEL=deepseek-chat                    # 可选，默认 deepseek-chat
.venv/bin/python agent.py "今天天气怎么样？"
# Windows / PowerShell：
#   $env:LLM_API_KEY="sk-xxx"
#   $env:LLM_BASE_URL="https://api.deepseek.com/v1"
#   $env:LLM_MODEL="deepseek-chat"
#   .venv\Scripts\python.exe agent.py "今天天气怎么样？"
```

`agent.py` 里值得读的关键代码：
- `to_openai_tool()`：把 MCP 工具定义转换成 LLM 认识的 function-calling schema
- `run_agent()`：核心循环 —— 把工具喂给 LLM → LLM 返回 tool_calls → 在 MCP 会话执行 → 结果回填 → 直到 LLM 给出最终回答

## 7. 远程部署（streamable-http）
本地 stdio 是"客户端拉起子进程、单机单客户端"；远程部署则是把同一个 MCP Server 跑成**常驻 Web 服务**，网络上的任何客户端都能连。适合：多客户端/团队共享、数据源在服务器侧、对外提供工具能力等场景。

### 启动服务
```bash
# Windows:  .venv\Scripts\python.exe deploy.py
# Linux:    .venv/bin/python deploy.py
python deploy.py                                   # 默认 0.0.0.0:8000，端点 /mcp
python deploy.py --host 0.0.0.0 --port 9000 --path /weather  # 自定义
```
启动后端点即 `http://<服务器IP>:8000/mcp`。v2 里传输参数直接传给 `mcp.run(transport="streamable-http", ...)`，业务代码零改动。

### 用 Inspector 远程连接
```bash
npx @modelcontextprotocol/inspector --transport http http://<服务器IP>:8000/mcp
```
浏览器打开 Inspector 后点 **Connect**，即可远程看到并调用两个工具。

### 接进 Cursor / Claude Desktop（URL 方式）
- **Cursor**：Settings → MCP → Add new MCP server → 选 `url`，填 `http://<服务器IP>:8000/mcp`
- **Claude Desktop**：在 MCP 配置里用远程 URL 方式（streamable-http 端点），地址同上

### 生产注意
- 本入口用于**演示/内网试用**；暴露公网前务必加**鉴权**（OAuth/JWT）、**限流**并前置 HTTPS（Nginx/Caddy 反代）。
- v2 在 host 为 `127.0.0.1` 时会自动开启 DNS rebinding 防护；对外部署需按需配置 `transport_security`。

## 8. 扩展方向

- 加 **Resource**：暴露静态数据（如"常用城市列表"）供客户端读取
- 加 **Prompt**：定义提示词模板，让客户端按模板引导 AI
- 换 **SSE 传输**：`mcp.run(transport='sse', ...)`（若需兼容老式 SSE 客户端）
- 换成你自己的真实业务接口（数据库、内网 API），原理完全一致

## 注意事项

- IP 定位返回的是**出口 IP 所在城市**，可能不等于物理位置；在公司/代理环境下尤其如此。
- 免费接口有限频，demo 场景够用；生产请申请正式 API key 或换商业服务。
- 本 demo 用到的外部接口（ipwho.is / open-meteo / github.com 等）在国内网络下**可能间歇性超时**，重试一两次通常就好，不是代码问题。
- **Windows 常见坑**：改完 `.vscode/mcp.json` 后必须 **Reload Window** 才生效；MCP 工具若没暴露给 Chat，先看 **MCP: List Servers** 状态 + Chat 输入框的 **Configure Tools**。

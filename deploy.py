#!/usr/bin/env python3
"""
streamable-http 部署入口：把 MCP Server 作为常驻 Web 服务暴露在网络上。

v2 里传输参数从构造函数挪到了 run() 上，因此只需以 streamable-http 启动同一个
server.py 里的 MCPServer 即可，无需改任何业务代码。

用法：
    python deploy.py                                # 默认 0.0.0.0:8000，端点 /mcp
    python deploy.py --host 0.0.0.0 --port 9000     # 自定义端口
    python deploy.py --path /weather                # 自定义端点路径

客户端远程连接：
    # MCP Inspector（图形化调试）
    npx @modelcontextprotocol/inspector --transport http http://<服务器IP>:8000/mcp

    # Cursor / Claude Desktop 等客户端配置远程 MCP server（URL 方式）
    http://<服务器IP>:8000/mcp

注意：生产环境部署务必再加一层鉴权/限流（见 README「远程部署」一节），
本入口仅用于演示与内网试用。
"""

import argparse

from server import mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="以 streamable-http 方式远程部署 MCP Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0（对外可访问）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    parser.add_argument("--path", default="/mcp", help="MCP 端点路径，默认 /mcp")
    args = parser.parse_args()

    print(f"== 启动 streamable-http MCP Server ==")
    print(f"   端点: http://{args.host}:{args.port}{args.path}")
    print(f"   本地验证: npx @modelcontextprotocol/inspector --transport http http://127.0.0.1:{args.port}{args.path}")
    print()

    # v2: 传输相关参数（host/port/path）直接传给 run()
    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path=args.path,
    )


if __name__ == "__main__":
    main()

"""MCP server generated from the tool registry. Exposes the same tools the chat
loop uses to Claude Code or any MCP client.

  homeai mcp                 # stdio (for `claude mcp add`)
  homeai mcp --http --port 5011
  HOMEAI_MCP_READONLY=1      # hide mutating tools
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from mcp.server import Server
from mcp.types import TextContent, Tool as McpTool

from .config import Config, load_config
from .db import connect, migrate
from .tools import registry

log = logging.getLogger("homeai.mcp")


def build_server(cfg: Config, readonly: bool) -> Server:
    app = Server("homeai")
    with connect(cfg.db_path) as c:
        migrate(c)

    @app.list_tools()
    async def list_tools() -> list[McpTool]:
        return [McpTool(name=t.name, description=t.description, inputSchema=t.parameters)
                for t in registry.TOOLS if not (readonly and t.mutating)]

    @app.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        conn = connect(cfg.db_path)
        try:
            out = registry.call_tool(conn, cfg, name, arguments or {}, allow_mutating=not readonly)
        finally:
            conn.close()
        return [TextContent(type="text", text=registry.to_text(out, limit=60000))]

    return app


def run_stdio(cfg: Config, readonly: bool) -> None:
    from mcp.server.stdio import stdio_server
    app = build_server(cfg, readonly)

    async def main():
        async with stdio_server() as (r, w):
            await app.run(r, w, app.create_initialization_options())
    asyncio.run(main())


def run_http(cfg: Config, readonly: bool, host: str, port: int) -> None:
    import contextlib
    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount
    app = build_server(cfg, readonly)
    manager = StreamableHTTPSessionManager(app=app, json_response=False, stateless=True)

    @contextlib.asynccontextmanager
    async def lifespan(_):
        async with manager.run():
            yield

    async def handle(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    uvicorn.run(Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    cfg = load_config()
    ro = os.environ.get("HOMEAI_MCP_READONLY", "0").lower() in ("1", "true", "yes")
    if "--http" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 5011
        run_http(cfg, ro, "127.0.0.1", port)
    else:
        run_stdio(cfg, ro)

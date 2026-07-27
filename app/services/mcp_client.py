import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MCP_SERVER_SCRIPT = PROJECT_ROOT / "mcp-server" / "server.py"


async def call_mcp_tool(tool_name: str, arguments: dict) -> str:
    env = os.environ.copy()
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(MCP_SERVER_SCRIPT)],
        env=env,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)
            if result.content and hasattr(result.content[0], "text"):
                return result.content[0].text
            return "[]"


async def get_forecast(date: str, location: str) -> dict:
    raw = await call_mcp_tool("get_forecast", {"date": date, "location": location})
    return json.loads(raw)


async def suggest_indoor_or_outdoor(date: str) -> list[dict]:
    raw = await call_mcp_tool("suggest_indoor_or_outdoor", {"date": date})
    return json.loads(raw)

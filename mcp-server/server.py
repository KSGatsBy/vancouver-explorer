"""STDIO MCP server exposing weather tools for Vancouver Summer Explorer."""

import json
import sys
from pathlib import Path

# Ensure mcp-server directory is on sys.path for local imports.
SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from mcp.server.fastmcp import FastMCP

import weather

mcp = FastMCP("vancouver-weather")


@mcp.tool()
def get_forecast(date: str, location: str) -> str:
    """Return weather condition and rain probability for a date and location.

    Args:
        date: Date in YYYY-MM-DD format.
        location: 'lat,lng' coordinates or 'Vancouver' for city center.
    """
    result = weather.get_forecast(date, location)
    return json.dumps(result)


@mcp.tool()
def suggest_indoor_or_outdoor(date: str) -> str:
    """Return per-activity indoor/outdoor recommendations for a day's itinerary.

    Args:
        date: Itinerary date in YYYY-MM-DD format.
    """
    result = weather.suggest_indoor_or_outdoor(date)
    return json.dumps(result)


if __name__ == "__main__":
    mcp.run(transport="stdio")

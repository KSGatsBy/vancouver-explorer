import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.services import mcp_client


def _seed_capilano(client, date="2026-08-01"):
    activity = client.post(
        "/activities",
        json={
            "name": "Capilano Suspension Bridge",
            "location": "North Vancouver",
            "cost": 65.0,
            "tags": ["outdoor"],
            "is_outdoor": True,
            "lat": 49.3427,
            "lng": -123.1147,
        },
    ).json()
    client.post(
        "/itinerary-entries",
        json={"date": date, "activity_id": activity["id"], "notes": "bring the camera"},
    )
    return activity


def test_itinerary_weather_endpoint(client):
    activity = client.post(
        "/activities",
        json={
            "name": "Capilano Suspension Bridge",
            "location": "North Vancouver",
            "is_outdoor": True,
            "lat": 49.3427,
            "lng": -123.1147,
        },
    ).json()

    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-01", "activity_id": activity["id"]},
    )

    mock_suggestions = [
        {
            "activity_id": activity["id"],
            "name": "Capilano Suspension Bridge",
            "rain_probability": 0.8,
            "recommendation": "indoor alternative suggested",
        }
    ]

    with patch(
        "app.services.mcp_client.suggest_indoor_or_outdoor",
        new=AsyncMock(return_value=mock_suggestions),
    ):
        response = client.get("/itinerary/2026-08-01/weather")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rain_probability"] == 0.8
    assert data[0]["recommendation"] == "indoor alternative suggested"


def test_itinerary_weather_404_for_unknown_day(client):
    assert client.get("/itinerary/2026-09-09/weather").status_code == 404


def test_weather_endpoint_returns_502_when_mcp_fails(client):
    _seed_capilano(client)
    with patch(
        "app.services.mcp_client.suggest_indoor_or_outdoor",
        new=AsyncMock(side_effect=RuntimeError("server died")),
    ):
        response = client.get("/itinerary/2026-08-01/weather")
    assert response.status_code == 502


# --- true end-to-end: spawns the real STDIO MCP server subprocess -------------
#
# Everything above stubs the MCP client out, so server.py itself is never
# exercised. These run the actual FastMCP STDIO server with WEATHER_OFFLINE=1
# so they resolve against the bundled cache and need no network.

def test_mcp_get_forecast_tool_over_stdio(monkeypatch):
    monkeypatch.setenv("WEATHER_OFFLINE", "1")

    raw = asyncio.run(
        mcp_client.call_mcp_tool(
            "get_forecast", {"date": "2026-08-01", "location": "49.3427,-123.1147"}
        )
    )
    forecast = json.loads(raw)

    assert forecast["source"] == "cached"
    assert forecast["rain_probability"] == 0.8
    assert forecast["condition"] == "rainy"


def test_mcp_suggest_tool_over_stdio_matches_demo_contract(client, monkeypatch):
    """The DESIGN.md magic moment, end to end through the real MCP server."""
    monkeypatch.setenv("WEATHER_OFFLINE", "1")
    activity = _seed_capilano(client)

    suggestions = asyncio.run(mcp_client.suggest_indoor_or_outdoor("2026-08-01"))

    assert len(suggestions) == 1
    assert suggestions[0]["activity_id"] == activity["id"]
    assert suggestions[0]["name"] == "Capilano Suspension Bridge"
    assert suggestions[0]["rain_probability"] == 0.8
    assert suggestions[0]["recommendation"] == "indoor alternative suggested"
    assert suggestions[0]["source"] == "cached"


def test_weather_endpoint_end_to_end_through_mcp_server(client, monkeypatch):
    """FastAPI -> MCP client -> STDIO server -> cached forecast, nothing mocked."""
    monkeypatch.setenv("WEATHER_OFFLINE", "1")
    activity = _seed_capilano(client)

    response = client.get("/itinerary/2026-08-01/weather")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["activity_id"] == activity["id"]
    assert data[0]["source"] == "cached"
    assert data[0]["recommendation"] == "indoor alternative suggested"

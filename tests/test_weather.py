import sys
from pathlib import Path
from unittest.mock import patch

import httpx

MCP_SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp-server"
if str(MCP_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER_DIR))

import weather  # noqa: E402


def test_get_forecast_live(client):
    mock_response = {
        "daily": {
            "time": ["2026-08-01"],
            "precipitation_probability_max": [80],
            "weather_code": [61],
        }
    }

    class MockHttpResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return mock_response

    with patch("weather.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value.__enter__.return_value.get.return_value = MockHttpResponse()
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert result["rain_probability"] == 0.8
    assert result["condition"] == "rainy"
    assert result["source"] == "live"


def test_get_forecast_cached_fallback(client):
    with patch("weather._fetch_live_forecast", side_effect=ConnectionError("offline")):
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert result["rain_probability"] == 0.8
    assert result["source"] == "cached"


def test_suggest_indoor_or_outdoor_demo_contract(client):
    create = client.post(
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
    )
    activity_id = create.json()["id"]

    client.post(
        "/itinerary-entries",
        json={
            "date": "2026-08-01",
            "activity_id": activity_id,
            "notes": "bring the camera",
        },
    )

    with patch("weather._fetch_live_forecast") as mock_live:
        mock_live.return_value = {
            "date": "2026-08-01",
            "location": "49.3427,-123.1147",
            "condition": "rainy",
            "rain_probability": 0.8,
            "source": "live",
        }
        suggestions = weather.suggest_indoor_or_outdoor("2026-08-01")

    assert len(suggestions) == 1
    assert suggestions[0]["activity_id"] == activity_id
    assert suggestions[0]["name"] == "Capilano Suspension Bridge"
    assert suggestions[0]["rain_probability"] == 0.8
    assert suggestions[0]["recommendation"] == "indoor alternative suggested"


def test_build_recommendation_outdoor_low_rain():
    assert weather.build_recommendation(True, 0.2) == "outdoor conditions look favorable"


def test_build_recommendation_indoor():
    assert (
        weather.build_recommendation(False, 0.9)
        == "indoor activity — weather unlikely to affect plans"
    )


def test_build_recommendation_unavailable_overrides_outdoor():
    assert (
        weather.build_recommendation(True, 0.0, "unavailable")
        == "forecast unavailable — plan flexibly"
    )


# --- offline / fallback paths -------------------------------------------------


def test_offline_env_var_forces_cached_path(monkeypatch):
    monkeypatch.setenv("WEATHER_OFFLINE", "1")
    with patch("weather.httpx.Client") as mock_client_cls:
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    mock_client_cls.assert_not_called()
    assert result["source"] == "cached"
    assert result["rain_probability"] == 0.8


def test_unknown_date_offline_degrades_instead_of_raising(monkeypatch):
    """A date with no live and no seeded forecast must not fail the whole day."""
    monkeypatch.setenv("WEATHER_OFFLINE", "1")
    result = weather.get_forecast("2030-01-01", "49.3427,-123.1147")

    assert result["source"] == "unavailable"
    assert result["condition"] == "unknown"
    assert result["rain_probability"] == 0.0


def test_suggest_survives_activity_with_no_forecast(client, monkeypatch):
    monkeypatch.setenv("WEATHER_OFFLINE", "1")
    activity = client.post(
        "/activities",
        json={
            "name": "Stanley Park Seawall",
            "location": "Vancouver",
            "is_outdoor": True,
            "lat": 49.3043,
            "lng": -123.1443,
        },
    ).json()
    client.post(
        "/itinerary-entries",
        json={"date": "2030-01-01", "activity_id": activity["id"]},
    )

    suggestions = weather.suggest_indoor_or_outdoor("2030-01-01")

    assert len(suggestions) == 1
    assert suggestions[0]["source"] == "unavailable"
    assert suggestions[0]["recommendation"] == "forecast unavailable — plan flexibly"


def test_parse_location_falls_back_on_garbage():
    assert weather.parse_location("not,coords") == (
        weather.VANCOUVER_LAT,
        weather.VANCOUVER_LNG,
    )
    assert weather.parse_location("") == (weather.VANCOUVER_LAT, weather.VANCOUVER_LNG)


# --- rate limiting / backoff --------------------------------------------------


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


_LIVE_PAYLOAD = {
    "daily": {
        "time": ["2026-08-01"],
        "precipitation_probability_max": [80],
        "weather_code": [61],
    }
}


def test_repeated_coordinates_hit_upstream_once():
    """suggest_indoor_or_outdoor must not re-query Open-Meteo per activity."""
    with patch("weather._fetch_live_forecast") as mock_live:
        mock_live.return_value = {
            "date": "2026-08-01",
            "location": "49.3427,-123.1147",
            "condition": "rainy",
            "rain_probability": 0.8,
            "source": "live",
        }
        first = weather.get_forecast("2026-08-01", "49.3427,-123.1147")
        second = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert mock_live.call_count == 1
    assert first == second


def test_transient_failure_retries_then_succeeds():
    with patch("weather.time.sleep") as mock_sleep, patch(
        "weather.httpx.Client"
    ) as mock_client_cls:
        mock_get = mock_client_cls.return_value.__enter__.return_value.get
        mock_get.side_effect = [
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            _StubResponse(_LIVE_PAYLOAD),
        ]
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert mock_get.call_count == 3
    assert result["source"] == "live"
    assert result["rain_probability"] == 0.8
    # Exponential backoff between the three attempts.
    assert [c.args[0] for c in mock_sleep.call_args_list] == [0.5, 1.0]


def test_exhausted_retries_fall_back_to_cache():
    with patch("weather.time.sleep"), patch("weather.httpx.Client") as mock_client_cls:
        mock_get = mock_client_cls.return_value.__enter__.return_value.get
        mock_get.side_effect = httpx.ConnectError("offline")
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert mock_get.call_count == weather.MAX_ATTEMPTS
    assert result["source"] == "cached"


def test_client_error_is_not_retried():
    """A 404 is permanent for a given request — don't burn retries on it."""
    request = httpx.Request("GET", weather.OPEN_METEO_URL)
    with patch("weather.time.sleep"), patch("weather.httpx.Client") as mock_client_cls:
        mock_get = mock_client_cls.return_value.__enter__.return_value.get
        mock_get.return_value = httpx.Response(404, request=request)
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert mock_get.call_count == 1
    assert result["source"] == "cached"


def test_rate_limit_response_is_retried():
    request = httpx.Request("GET", weather.OPEN_METEO_URL)
    with patch("weather.time.sleep"), patch("weather.httpx.Client") as mock_client_cls:
        mock_get = mock_client_cls.return_value.__enter__.return_value.get
        mock_get.side_effect = [
            httpx.Response(429, request=request),
            _StubResponse(_LIVE_PAYLOAD),
        ]
        result = weather.get_forecast("2026-08-01", "49.3427,-123.1147")

    assert mock_get.call_count == 2
    assert result["source"] == "live"

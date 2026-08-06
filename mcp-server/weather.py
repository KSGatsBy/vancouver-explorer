import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_PATH = Path(__file__).resolve().parent / "cached_forecast.json"
RAIN_THRESHOLD = 0.5
VANCOUVER_LAT = 49.2827
VANCOUVER_LNG = -123.1207

# Backoff/rate-limiting for Open-Meteo (no API key, but be a good citizen).
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5
MEMO_TTL_SECONDS = 300.0

# WMO weather codes commonly associated with precipitation.
RAIN_WEATHER_CODES = {
    51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99
}

# (date, lat, lng) -> (expires_at, forecast). Collapses the N-activities-at-one-
# location case in suggest_indoor_or_outdoor into a single upstream call.
_FORECAST_MEMO: dict[tuple[str, float, float], tuple[float, dict[str, Any]]] = {}


def offline_mode() -> bool:
    """True when WEATHER_OFFLINE forces the cached path (tests/demo without network)."""
    return os.environ.get("WEATHER_OFFLINE", "").strip().lower() in {"1", "true", "yes"}


def clear_memo() -> None:
    _FORECAST_MEMO.clear()


def parse_location(location: str) -> tuple[float, float]:
    """Parse 'lat,lng', falling back to Vancouver center for blank/unparseable input."""
    location = (location or "").strip()
    if not location or location.lower() == "vancouver":
        return VANCOUVER_LAT, VANCOUVER_LNG
    if "," in location:
        lat_str, lng_str = location.split(",", 1)
        try:
            return float(lat_str.strip()), float(lng_str.strip())
        except ValueError:
            return VANCOUVER_LAT, VANCOUVER_LNG
    return VANCOUVER_LAT, VANCOUVER_LNG


def _load_cached_forecasts() -> list[dict[str, Any]]:
    try:
        with CACHE_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return data.get("forecasts", [])


def _find_cached_forecast(date: str, lat: float, lng: float) -> dict[str, Any] | None:
    forecasts = _load_cached_forecasts()
    for entry in forecasts:
        if entry["date"] != date:
            continue
        if abs(entry["lat"] - lat) < 0.01 and abs(entry["lng"] - lng) < 0.01:
            return entry
    # No coordinate match: any seeded forecast for that date beats nothing at all.
    for entry in forecasts:
        if entry["date"] == date:
            return entry
    return None


def _condition_from_weather_code(code: int | None, rain_probability: float) -> str:
    if rain_probability >= RAIN_THRESHOLD:
        return "rainy"
    if code in RAIN_WEATHER_CODES:
        return "rainy"
    if code in {0, 1}:
        return "clear"
    if code in {2, 3}:
        return "partly cloudy"
    if code in {45, 48}:
        return "foggy"
    return "cloudy"


def _get_with_backoff(params: dict[str, Any]) -> dict[str, Any]:
    """GET Open-Meteo, retrying transient failures with exponential backoff.

    4xx responses (other than 429) are permanent for a given request, so they
    fail fast instead of burning retries.
    """
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(OPEN_METEO_URL, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status != 429 and 400 <= status < 500:
                raise
            last_error = exc
        except (httpx.HTTPError, OSError, ValueError) as exc:
            last_error = exc

        if attempt < MAX_ATTEMPTS - 1:
            time.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

    raise last_error if last_error else RuntimeError("Open-Meteo request failed")


def _fetch_live_forecast(date: str, lat: float, lng: float) -> dict[str, Any]:
    if offline_mode():
        raise RuntimeError("WEATHER_OFFLINE is set; skipping live Open-Meteo call")

    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": "weather_code,precipitation_probability_max,uv_index_max",
        "start_date": date,
        "end_date": date,
        "timezone": "America/Vancouver",
    }
    payload = _get_with_backoff(params)

    daily = payload.get("daily", {})
    times = daily.get("time", [])
    if date not in times:
        raise ValueError(f"No forecast available for {date}")

    index = times.index(date)
    rain_pct = daily.get("precipitation_probability_max", [0])[index]
    weather_code = daily.get("weather_code", [None])[index]
    uv_list = daily.get("uv_index_max", [5.0])
    uv_val = float(uv_list[index] if len(uv_list) > index and uv_list[index] is not None else 5.0)

    rain_probability = round(float(rain_pct or 0) / 100.0, 2)
    condition = _condition_from_weather_code(weather_code, rain_probability)

    return {
        "date": date,
        "location": f"{lat},{lng}",
        "condition": condition,
        "rain_probability": rain_probability,
        "uv_index": uv_val,
        "source": "live",
    }


def get_forecast(date: str, location: str) -> dict[str, Any]:
    lat, lng = parse_location(location)
    memo_key = (date, round(lat, 3), round(lng, 3))

    memoized = _FORECAST_MEMO.get(memo_key)
    if memoized and memoized[0] > time.monotonic():
        return dict(memoized[1])

    try:
        forecast = _fetch_live_forecast(date, lat, lng)
    except Exception:
        cached = _find_cached_forecast(date, lat, lng)
        if cached is None:
            return {
                "date": date,
                "location": f"{lat},{lng}",
                "condition": "unknown",
                "rain_probability": 0.0,
                "uv_index": 5.0,
                "source": "unavailable",
            }
        forecast = {
            "date": date,
            "location": f"{lat},{lng}",
            "condition": cached["condition"],
            "rain_probability": cached["rain_probability"],
            "uv_index": cached.get("uv_index", 5.0),
            "source": "cached",
        }

    _FORECAST_MEMO[memo_key] = (time.monotonic() + MEMO_TTL_SECONDS, dict(forecast))
    return forecast


def build_recommendation(
    is_outdoor: bool, rain_probability: float, source: str = "live", uv_index: float = 5.0
) -> str:
    if source == "unavailable":
        return "forecast unavailable — plan flexibly"
    if is_outdoor and rain_probability >= RAIN_THRESHOLD:
        return "indoor alternative suggested"
    if is_outdoor and uv_index >= 6.0:
        return f"high UV index ({uv_index}) — sun protection recommended"
    if is_outdoor:
        return "outdoor conditions look favorable"
    return "indoor activity — weather unlikely to affect plans"


def get_transit_advice(is_outdoor: bool, rain_probability: float, uv_index: float = 5.0) -> str:
    if is_outdoor and rain_probability >= RAIN_THRESHOLD:
        return "🚆 TransLink Transit Advice: High chance of rain. Take SkyTrain (Expo/Canada Line) & use covered concourses."
    if is_outdoor and uv_index >= 6.0:
        return "🕶️ TransLink Transit Advice: High UV index. Prefer air-conditioned SeaBus / SkyTrain transit."
    return ""


def suggest_indoor_or_outdoor(date: str) -> list[dict[str, Any]]:
    """Per-activity recommendations for every itinerary entry on ``date``."""
    from db import get_itinerary_activities_for_date

    activities = get_itinerary_activities_for_date(date)
    suggestions: list[dict[str, Any]] = []

    for activity in activities:
        location = f"{activity['lat']},{activity['lng']}"
        forecast = get_forecast(date, location)
        rain_probability = forecast["rain_probability"]
        uv_index = forecast.get("uv_index", 5.0)
        source = forecast["source"]
        suggestions.append(
            {
                "activity_id": activity["activity_id"],
                "name": activity["name"],
                "condition": forecast["condition"],
                "rain_probability": rain_probability,
                "uv_index": uv_index,
                "source": source,
                "recommendation": build_recommendation(
                    activity["is_outdoor"], rain_probability, source, uv_index
                ),
                "transit_advice": get_transit_advice(
                    activity["is_outdoor"], rain_probability, uv_index
                ),
            }
        )
    return suggestions

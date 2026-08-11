"""Tests for app.services.llm_engine System Prompts & Rule Fallback Engine."""

import pytest
from app.services.llm_engine import (
    haversine_km,
    run_ai_plan,
    run_smart_swap,
    run_weather_advisory,
)


def test_haversine_km():
    # Distance between Vancouver downtown center (49.2827, -123.1207) and Capilano Suspension Bridge (49.3427, -123.1147)
    dist = haversine_km(49.2827, -123.1207, 49.3427, -123.1147)
    assert 6.0 <= dist <= 7.5


def test_run_smart_swap_tier1_match():
    outdoor = {
        "id": 1,
        "name": "Capilano Suspension Bridge",
        "is_outdoor": True,
        "cost": 65.0,
        "lat": 49.3427,
        "lng": -123.1147,
    }
    indoor_candidates = [
        {
            "id": 2,
            "name": "Nearby Art Museum",
            "is_outdoor": False,
            "cost": 60.0,
            "lat": 49.3450,
            "lng": -123.1150,  # ~0.3km away, cost diff 5.0 (<= 13.0) -> Tier 1
        },
        {
            "id": 3,
            "name": "Distant Indoor Market",
            "is_outdoor": False,
            "cost": 0.0,
            "lat": 49.2800,
            "lng": -123.1200,  # >5km away
        },
    ]

    res = run_smart_swap(outdoor, indoor_candidates, group_size=1)
    assert res["status"] == "success"
    assert res["original_activity_id"] == 1
    assert res["swapped_activity"]["id"] == 2
    assert res["swapped_activity"]["tier_matched"] == "Tier 1"
    assert "TransLink" in res["transit_suggestion"]


def test_run_smart_swap_no_candidates():
    outdoor = {"id": 1, "name": "Park", "is_outdoor": True, "cost": 0.0}
    res = run_smart_swap(outdoor, [], group_size=1)
    assert res["status"] == "no_match_found"
    assert res["swapped_activity"] is None


def test_run_ai_plan_rainy_weather_avoidance():
    weather_data = [{"rain_probability": 0.8}]
    library = [
        {"id": 1, "name": "Outdoor Hiking", "is_outdoor": True, "cost": 0.0, "tags": ["outdoor"]},
        {"id": 2, "name": "Art Gallery", "is_outdoor": False, "cost": 25.0, "tags": ["art", "museum"]},
        {"id": 3, "name": "Science Center", "is_outdoor": False, "cost": 30.0, "tags": ["museum"]},
    ]

    res = run_ai_plan(
        date="2026-08-15",
        max_budget=100.0,
        preference="outdoor",
        group_size=1,
        weather_data=weather_data,
        activity_library=library,
    )

    selected_ids = [a["id"] for a in res["selected_activities"]]
    assert 1 not in selected_ids  # Outdoor activity 1 must be avoided on rainy days
    assert 2 in selected_ids
    assert res["weather_risk_level"] == "High"


def test_run_weather_advisory_rain_and_uv():
    daily_activities = [
        {"id": 101, "name": "Outdoor Park", "is_outdoor": True},
    ]
    mcp_weather = [
        {"activity_id": 101, "rain_probability": 0.7, "uv_index": 7.0},
    ]

    res = run_weather_advisory("2026-08-15", daily_activities, mcp_weather)
    assert res["rain_risk"] is True
    assert res["high_risk_activity_ids"] == [101]
    assert "TransLink" in res["transit_advice"]

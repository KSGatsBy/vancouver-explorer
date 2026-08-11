from fastapi import APIRouter, HTTPException

from app.db import get_connection, row_to_activity
from app.models import (
    AIPlanRequest,
    AIPlanResponse,
    ActivityResponse,
    ItineraryDayPatch,
    ItineraryDayResponse,
    ItineraryEntryCreate,
    ItineraryEntryPatch,
    ItineraryEntryResponse,
    SmartSwapResponse,
    WeatherAdvisoryResponse,
    WeatherSuggestion,
    validate_iso_date,
)
from app.services.cost import compute_total_cost
from app.services import llm_engine, mcp_client

router = APIRouter(tags=["itinerary"])


def _activity_response(row) -> ActivityResponse:
    return ActivityResponse(**row_to_activity(row))


def _get_day_or_404(conn, date: str):
    day = conn.execute(
        "SELECT date, group_size FROM itinerary_days WHERE date = ?", (date,)
    ).fetchone()
    if not day:
        raise HTTPException(status_code=404, detail="Itinerary day not found")
    return day


def _build_day_response(conn, date: str) -> ItineraryDayResponse:
    day = _get_day_or_404(conn, date)
    rows = conn.execute(
        """
        SELECT e.id, e.activity_id, e.notes, e.rating, a.*
        FROM itinerary_entries e
        JOIN activities a ON a.id = e.activity_id
        WHERE e.day_id = ?
        ORDER BY e.id
        """,
        (date,),
    ).fetchall()

    entries: list[ItineraryEntryResponse] = []
    costs: list[float | None] = []
    for row in rows:
        activity = row_to_activity(row)
        entries.append(
            ItineraryEntryResponse(
                id=row["id"],
                activity_id=row["activity_id"],
                activity=ActivityResponse(**activity),
                notes=row["notes"],
                rating=row["rating"],
            )
        )
        costs.append(activity["cost"])

    return ItineraryDayResponse(
        date=day["date"],
        group_size=day["group_size"],
        entries=entries,
        total_cost=compute_total_cost(costs, day["group_size"]),
    )


@router.get("/itinerary/{date}", response_model=ItineraryDayResponse)
def get_itinerary(date: str):
    with get_connection() as conn:
        return _build_day_response(conn, date)


@router.get("/itinerary/{date}/weather", response_model=list[WeatherSuggestion])
async def get_itinerary_weather(date: str):
    with get_connection() as conn:
        _get_day_or_404(conn, date)
    try:
        suggestions = await mcp_client.suggest_indoor_or_outdoor(date)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Weather service unavailable: {exc}",
        ) from exc
    return [WeatherSuggestion(**item) for item in suggestions]


@router.get("/itinerary/{date}/weather-advisory", response_model=WeatherAdvisoryResponse)
async def get_itinerary_weather_advisory(date: str):
    with get_connection() as conn:
        _get_day_or_404(conn, date)
        rows = conn.execute(
            """
            SELECT e.activity_id, a.name, a.is_outdoor, a.lat, a.lng
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.day_id = ?
            """,
            (date,),
        ).fetchall()
        daily_activities = [dict(r) for r in rows]

    try:
        suggestions = await mcp_client.suggest_indoor_or_outdoor(date)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Weather service unavailable: {exc}",
        ) from exc

    advisory_data = llm_engine.run_weather_advisory(date, daily_activities, suggestions)
    advisory_data["suggestions"] = [WeatherSuggestion(**item) for item in suggestions]
    return WeatherAdvisoryResponse(**advisory_data)


@router.post("/itinerary/{date}/smart-swap", response_model=SmartSwapResponse)
async def smart_swap_itinerary(date: str):
    with get_connection() as conn:
        day = _get_day_or_404(conn, date)
        group_size = day["group_size"]
        
        # 1. Fetch weather suggestions
        try:
            suggestions = await mcp_client.suggest_indoor_or_outdoor(date)
        except Exception:
            suggestions = []
            
        rain_activity_ids = {
            item["activity_id"] for item in suggestions if item.get("rain_probability", 0) >= 0.5
        }

        # 2. Get outdoor entries for this date
        entries = conn.execute(
            """
            SELECT e.id, e.activity_id, a.name, a.is_outdoor, a.lat, a.lng, a.cost
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.day_id = ?
            """,
            (date,),
        ).fetchall()

        # 3. Find indoor activities available in catalog
        indoor_rows = conn.execute(
            "SELECT * FROM activities WHERE is_outdoor = 0 ORDER BY id"
        ).fetchall()

        scheduled_activity_ids = {e["activity_id"] for e in entries}
        indoor_candidates = [
            row_to_activity(r) for r in indoor_rows if r["id"] not in scheduled_activity_ids
        ]

        target_entry = None
        for entry in entries:
            if entry["is_outdoor"] and entry["activity_id"] in rain_activity_ids:
                target_entry = entry
                break

        if not target_entry:
            # Fallback to any outdoor entry if no explicit weather match
            for entry in entries:
                if entry["is_outdoor"]:
                    target_entry = entry
                    break

        if not target_entry:
            return SmartSwapResponse(
                status="no_match_found",
                original_activity_id=0,
                swapped_activity=None,
                swap_reason="当前行程中无下雨风向的户外活动需要替换。",
                transit_suggestion="全天行程安全，无需更换活动。",
                updated_itinerary=_build_day_response(conn, date),
            )

        outdoor_dict = dict(target_entry)
        swap_result = llm_engine.run_smart_swap(outdoor_dict, indoor_candidates, group_size)

        if swap_result.get("status") == "success" and swap_result.get("swapped_activity"):
            swapped_info = swap_result["swapped_activity"]
            swapped_id = swapped_info["id"]
            conn.execute(
                """
                UPDATE itinerary_entries 
                SET activity_id = ?, notes = ?
                WHERE id = ?
                """,
                (
                    swapped_id,
                    f"☔ Swapped ({swapped_info['tier_matched']}: {swapped_info['name']})",
                    target_entry["id"],
                ),
            )
            conn.commit()

        updated_day = _build_day_response(conn, date)
        swap_result["updated_itinerary"] = updated_day
        return SmartSwapResponse(**swap_result)


@router.post("/itinerary/{date}/ai-plan", response_model=AIPlanResponse)
async def ai_plan_itinerary(date: str, body: AIPlanRequest):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO itinerary_days (date, group_size) VALUES (?, 1)",
            (date,),
        )
        day = conn.execute(
            "SELECT group_size FROM itinerary_days WHERE date = ?", (date,)
        ).fetchone()
        group_size = day["group_size"] if day else 1

        try:
            suggestions = await mcp_client.suggest_indoor_or_outdoor(date)
        except Exception:
            suggestions = []

        activities = conn.execute("SELECT * FROM activities").fetchall()
        parsed_activities = [row_to_activity(a) for a in activities]

        ai_plan_result = llm_engine.run_ai_plan(
            date=date,
            max_budget=body.max_budget,
            preference=body.preference,
            group_size=group_size,
            weather_data=suggestions,
            activity_library=parsed_activities,
        )

        selected = ai_plan_result.get("selected_activities", [])
        conn.execute("DELETE FROM itinerary_entries WHERE day_id = ?", (date,))
        for a in selected:
            conn.execute(
                "INSERT INTO itinerary_entries (day_id, activity_id, notes) VALUES (?, ?, ?)",
                (date, a["id"], f"🤖 AI Planned ({body.preference.capitalize()})"),
            )
        conn.commit()

        ai_plan_result["updated_itinerary"] = _build_day_response(conn, date)
        return AIPlanResponse(**ai_plan_result)





@router.post("/itinerary-entries", response_model=ItineraryEntryResponse, status_code=201)
def create_itinerary_entry(body: ItineraryEntryCreate):
    with get_connection() as conn:
        activity = conn.execute(
            "SELECT * FROM activities WHERE id = ?", (body.activity_id,)
        ).fetchone()
        if not activity:
            raise HTTPException(status_code=404, detail="Activity not found")

        conn.execute(
            "INSERT OR IGNORE INTO itinerary_days (date, group_size) VALUES (?, 1)",
            (body.date,),
        )
        existing_entry = conn.execute(
            "SELECT id FROM itinerary_entries WHERE day_id = ? AND activity_id = ?",
            (body.date, body.activity_id),
        ).fetchone()
        if existing_entry:
            raise HTTPException(
                status_code=400,
                detail="This activity is already scheduled for this date.",
            )

        cursor = conn.execute(
            """
            INSERT INTO itinerary_entries (day_id, activity_id, notes)
            VALUES (?, ?, ?)
            """,
            (body.date, body.activity_id, body.notes),
        )
        conn.commit()
        row = conn.execute(
            """
            SELECT e.id, e.activity_id, e.notes, e.rating, a.*
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.id = ?
            """,
            (cursor.lastrowid,),
        ).fetchone()

    activity_data = row_to_activity(row)
    return ItineraryEntryResponse(
        id=row["id"],
        activity_id=row["activity_id"],
        activity=ActivityResponse(**activity_data),
        notes=row["notes"],
        rating=row["rating"],
    )


@router.patch("/itinerary-entries/{entry_id}", response_model=ItineraryEntryResponse)
def patch_itinerary_entry(entry_id: int, body: ItineraryEntryPatch):
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM itinerary_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Itinerary entry not found")

        if "notes" in updates:
            conn.execute(
                "UPDATE itinerary_entries SET notes = ? WHERE id = ?",
                (updates["notes"], entry_id),
            )
        if "rating" in updates:
            conn.execute(
                "UPDATE itinerary_entries SET rating = ? WHERE id = ?",
                (updates["rating"], entry_id),
            )
        conn.commit()

        row = conn.execute(
            """
            SELECT e.id, e.activity_id, e.notes, e.rating, a.*
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.id = ?
            """,
            (entry_id,),
        ).fetchone()

    activity_data = row_to_activity(row)
    return ItineraryEntryResponse(
        id=row["id"],
        activity_id=row["activity_id"],
        activity=ActivityResponse(**activity_data),
        notes=row["notes"],
        rating=row["rating"],
    )


@router.patch("/itinerary/{date}", response_model=ItineraryDayResponse)
def patch_itinerary_day(date: str, body: ItineraryDayPatch):
    try:
        validate_iso_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO itinerary_days (date, group_size) VALUES (?, ?)
            ON CONFLICT(date) DO UPDATE SET group_size = excluded.group_size
            """,
            (date, body.group_size),
        )
        conn.commit()
        return _build_day_response(conn, date)


@router.delete("/itinerary-entries/{entry_id}", status_code=204)
def delete_itinerary_entry(entry_id: int):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM itinerary_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Itinerary entry not found")

        conn.execute("DELETE FROM itinerary_entries WHERE id = ?", (entry_id,))
        conn.commit()

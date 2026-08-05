from fastapi import APIRouter, HTTPException

from app.db import get_connection, row_to_activity
from app.models import (
    AIPlanRequest,
    ActivityResponse,
    ItineraryDayPatch,
    ItineraryDayResponse,
    ItineraryEntryCreate,
    ItineraryEntryPatch,
    ItineraryEntryResponse,
    WeatherSuggestion,
    validate_iso_date,
)
from app.services.cost import compute_total_cost
from app.services import mcp_client

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


@router.post("/itinerary/{date}/smart-swap", response_model=ItineraryDayResponse)
async def smart_swap_itinerary(date: str):
    with get_connection() as conn:
        _get_day_or_404(conn, date)
        
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
            SELECT e.id, e.activity_id, a.is_outdoor
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.day_id = ?
            """,
            (date,),
        ).fetchall()

        # 3. Find indoor activities available in catalog
        indoor_activities = conn.execute(
            "SELECT * FROM activities WHERE is_outdoor = 0 ORDER BY id"
        ).fetchall()

        # Existing activity IDs scheduled on this date
        scheduled_activity_ids = {e["activity_id"] for e in entries}

        swapped_count = 0
        for entry in entries:
            if entry["is_outdoor"] and entry["activity_id"] in rain_activity_ids:
                # Find an indoor activity not currently scheduled on this day
                available_indoor = next(
                    (ia for ia in indoor_activities if ia["id"] not in scheduled_activity_ids),
                    None
                )
                if available_indoor:
                    conn.execute(
                        """
                        UPDATE itinerary_entries 
                        SET activity_id = ?, notes = '☔ Swapped for rain protection'
                        WHERE id = ?
                        """,
                        (available_indoor["id"], entry["id"]),
                    )
                    scheduled_activity_ids.remove(entry["activity_id"])
                    scheduled_activity_ids.add(available_indoor["id"])
                    swapped_count += 1

        conn.commit()
        return _build_day_response(conn, date)


@router.post("/itinerary/{date}/ai-plan", response_model=ItineraryDayResponse)
async def ai_plan_itinerary(date: str, body: AIPlanRequest):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO itinerary_days (date, group_size) VALUES (?, 1)",
            (date,),
        )

        try:
            suggestions = await mcp_client.suggest_indoor_or_outdoor(date)
        except Exception:
            suggestions = []

        is_rainy = any(item.get("rain_probability", 0) >= 0.5 for item in suggestions)

        activities = conn.execute("SELECT * FROM activities").fetchall()
        parsed_activities = [row_to_activity(a) for a in activities]

        candidates = []
        pref = body.preference.lower()

        for a in parsed_activities:
            cost = a["cost"] or 0.0
            score = 0
            is_out = a["is_outdoor"]
            tags = [t.lower() for t in a.get("tags", [])]

            if is_rainy and is_out:
                score -= 10
            elif not is_rainy and is_out:
                score += 5

            if pref == "outdoor" and is_out and not is_rainy:
                score += 10
            elif pref == "museum" and (not is_out or any(t in ["museum", "art", "gallery", "indoor"] for t in tags)):
                score += 10
            elif pref == "food" and any(t in ["food", "market", "cafe", "chill", "dining"] for t in tags):
                score += 10
            elif pref == "free" and cost == 0:
                score += 10

            candidates.append((score, a))

        candidates.sort(key=lambda x: x[0], reverse=True)

        selected = []
        current_cost = 0.0
        for score, a in candidates:
            c = a["cost"] or 0.0
            if current_cost + c <= body.max_budget or not selected:
                selected.append(a)
                current_cost += c
                if len(selected) >= 3:
                    break

        conn.execute("DELETE FROM itinerary_entries WHERE day_id = ?", (date,))
        for a in selected:
            conn.execute(
                "INSERT INTO itinerary_entries (day_id, activity_id, notes) VALUES (?, ?, ?)",
                (date, a["id"], f"🤖 AI Planned ({body.preference.capitalize()})"),
            )

        conn.commit()
        return _build_day_response(conn, date)




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

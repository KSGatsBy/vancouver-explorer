from fastapi import APIRouter, HTTPException

from app.db import get_connection, row_to_activity
from app.models import (
    ActivityResponse,
    ItineraryDayResponse,
    ItineraryEntryCreate,
    ItineraryEntryPatch,
    ItineraryEntryResponse,
    WeatherSuggestion,
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

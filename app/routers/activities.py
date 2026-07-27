import json

from fastapi import APIRouter, HTTPException, Query

from app.db import (
    VANCOUVER_LAT,
    VANCOUVER_LNG,
    get_connection,
    row_to_activity,
)
from app.models import ActivityCreate, ActivityResponse, ActivityUpdate
from app.services.tags import filter_activities_by_tags

router = APIRouter(prefix="/activities", tags=["activities"])


def _resolve_coords(lat: float | None, lng: float | None) -> tuple[float, float]:
    if lat is None and lng is None:
        return VANCOUVER_LAT, VANCOUVER_LNG
    if lat is None or lng is None:
        raise HTTPException(
            status_code=422,
            detail="Both lat and lng must be provided together, or omit both for defaults",
        )
    return lat, lng


def _to_response(activity: dict) -> ActivityResponse:
    return ActivityResponse(**activity)


@router.get("", response_model=list[ActivityResponse])
def list_activities(tag: str | None = Query(default=None)):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM activities ORDER BY id"
        ).fetchall()
    activities = [row_to_activity(row) for row in rows]
    if tag:
        filter_tags = [t.strip() for t in tag.split(",") if t.strip()]
        activities = filter_activities_by_tags(activities, filter_tags)
    return [_to_response(a) for a in activities]


@router.post("", response_model=ActivityResponse, status_code=201)
def create_activity(body: ActivityCreate):
    lat, lng = _resolve_coords(body.lat, body.lng)
    tags_json = json.dumps(body.tags)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO activities (name, location, cost, tags, is_outdoor, lat, lng)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                body.name,
                body.location,
                body.cost,
                tags_json,
                int(body.is_outdoor),
                lat,
                lng,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM activities WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return _to_response(row_to_activity(row))


@router.put("/{activity_id}", response_model=ActivityResponse)
def update_activity(activity_id: int, body: ActivityUpdate):
    lat, lng = _resolve_coords(body.lat, body.lng)
    tags_json = json.dumps(body.tags)
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Activity not found")
        conn.execute(
            """
            UPDATE activities
            SET name = ?, location = ?, cost = ?, tags = ?, is_outdoor = ?, lat = ?, lng = ?
            WHERE id = ?
            """,
            (
                body.name,
                body.location,
                body.cost,
                tags_json,
                int(body.is_outdoor),
                lat,
                lng,
                activity_id,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
    return _to_response(row_to_activity(row))


@router.delete("/{activity_id}", status_code=204)
def delete_activity(activity_id: int):
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Activity not found")
        conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
        conn.commit()

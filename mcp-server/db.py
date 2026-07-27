import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

VANCOUVER_LAT = 49.2827
VANCOUVER_LNG = -123.1207

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "vancouver_explorer.db"


def get_db_path() -> Path:
    return Path(os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH))


@contextmanager
def get_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_itinerary_activities_for_date(date: str) -> list[dict[str, Any]]:
    """Return activities scheduled on a date, joined from itinerary entries."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                a.id AS activity_id,
                a.name,
                a.is_outdoor,
                a.lat,
                a.lng
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.day_id = ?
            ORDER BY e.id
            """,
            (date,),
        ).fetchall()
    return [
        {
            "activity_id": row["activity_id"],
            "name": row["name"],
            "is_outdoor": bool(row["is_outdoor"]),
            "lat": row["lat"] if row["lat"] is not None else VANCOUVER_LAT,
            "lng": row["lng"] if row["lng"] is not None else VANCOUVER_LNG,
        }
        for row in rows
    ]

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

VANCOUVER_LAT = 49.2827
VANCOUVER_LNG = -123.1207

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "vancouver_explorer.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    location TEXT NOT NULL,
    cost REAL,
    tags TEXT,
    is_outdoor BOOLEAN DEFAULT 0,
    lat REAL,
    lng REAL
);

CREATE TABLE IF NOT EXISTS itinerary_days (
    date TEXT PRIMARY KEY,
    group_size INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS itinerary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id TEXT REFERENCES itinerary_days(date),
    activity_id INTEGER REFERENCES activities(id),
    notes TEXT,
    rating INTEGER
);
"""


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


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def row_to_activity(row: sqlite3.Row) -> dict[str, Any]:
    tags_raw = row["tags"]
    tags = json.loads(tags_raw) if tags_raw else []
    return {
        "id": row["id"],
        "name": row["name"],
        "location": row["location"],
        "cost": row["cost"],
        "tags": tags,
        "is_outdoor": bool(row["is_outdoor"]),
        "lat": row["lat"],
        "lng": row["lng"],
    }

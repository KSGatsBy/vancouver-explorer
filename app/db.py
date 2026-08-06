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
    conn = sqlite3.connect(get_db_path(), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def seed_initial_data(force: bool = False) -> int:
    """Pre-populates 10 classic Vancouver destinations if activities table is empty."""
    if "PYTEST_CURRENT_TEST" in os.environ and not force:
        return 0

    with get_connection() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM activities")
        if cursor.fetchone()[0] > 0 and not force:
            return 0

        initial_activities = [
            ("Stanley Park", "Downtown Vancouver", 0.0, ["outdoor", "park", "nature", "free"], 1, 49.3017, -123.1417),
            ("Capilano Suspension Bridge", "North Vancouver", 66.95, ["outdoor", "nature", "bridge", "paid"], 1, 49.3427, -123.1147),
            ("Science World", "False Creek", 33.20, ["indoor", "museum", "family", "paid"], 0, 49.2734, -123.1038),
            ("Granville Island Public Market", "Granville Island", 0.0, ["indoor", "food", "market", "free"], 0, 49.2712, -123.1340),
            ("Grouse Mountain Resort", "North Vancouver", 79.00, ["outdoor", "mountain", "hiking", "paid"], 1, 49.3797, -123.0984),
            ("Vancouver Art Gallery", "Downtown Vancouver", 29.00, ["indoor", "art", "museum", "paid"], 0, 49.2829, -123.1205),
            ("Kitsilano Beach", "Kitsilano", 0.0, ["outdoor", "beach", "summer", "free"], 1, 49.2743, -123.1552),
            ("Bloedel Conservatory", "Queen Elizabeth Park", 7.80, ["indoor", "nature", "garden", "paid"], 0, 49.2423, -123.1144),
            ("Gastown Steam Clock", "Gastown", 0.0, ["outdoor", "landmark", "history", "free"], 1, 49.2844, -123.1089),
            ("Museum of Anthropology", "UBC Campus", 18.00, ["indoor", "museum", "history", "paid"], 0, 49.2695, -123.2595),
        ]

        conn.executemany(
            """
            INSERT INTO activities (name, location, cost, tags, is_outdoor, lat, lng)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (name, loc, cost, json.dumps(tags), is_out, lat, lng)
                for name, loc, cost, tags, is_out, lat, lng in initial_activities
            ]
        )
        conn.commit()
        return len(initial_activities)


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()
    seed_initial_data()
    cleanup_duplicates()


def cleanup_duplicates() -> int:
    """Removes any duplicate itinerary entries (same day_id and activity_id), keeping the earliest entry."""
    with get_connection() as conn:
        cursor = conn.execute(
            """
            DELETE FROM itinerary_entries 
            WHERE id NOT IN (
                SELECT MIN(id) 
                FROM itinerary_entries 
                GROUP BY day_id, activity_id
            )
            """
        )
        conn.commit()
        return cursor.rowcount


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

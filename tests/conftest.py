import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Use an isolated temp database for every test session.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_PATH"] = _tmp.name

# The MCP server is a standalone script dir, not a package — put it on sys.path
# so tests can import `weather`/`db` the same way server.py does.
MCP_SERVER_DIR = Path(__file__).resolve().parent.parent / "mcp-server"
if str(MCP_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(MCP_SERVER_DIR))

from app.db import VANCOUVER_LAT, VANCOUVER_LNG, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    init_db()
    yield
    Path(_tmp.name).unlink(missing_ok=True)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_activities():
    from app.db import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM itinerary_entries")
        conn.execute("DELETE FROM itinerary_days")
        conn.execute("DELETE FROM activities")
        conn.commit()


@pytest.fixture(autouse=True)
def clear_forecast_memo():
    """The in-process forecast cache must not leak results across tests."""
    import weather

    weather.clear_memo()
    yield
    weather.clear_memo()

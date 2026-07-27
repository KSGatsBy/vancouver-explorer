# Vancouver Summer Explorer - Development Guide

## Project Tech Stack
- **Backend:** FastAPI (Python), SQLite
- **MCP Server:** Python STDIO MCP Server wrapping Open-Meteo API
- **Frontend:** HTML / JS (Simple Single Page Application)
- **Testing:** pytest (Unit & Integration)

## Key Rules & Constraints
1. **Database:** Use parameterized SQL queries ONLY (prevent SQL injection).
2. **MCP Integration:** Must expose `get_forecast` and `suggest_indoor_or_outdoor`. Open-Meteo requires no API key. Always implement graceful fallback to cached data when offline.
3. **Data Model Rules:**
   - Activities missing lat/lng should default to Vancouver center (49.2827, -123.1207).
   - `total_cost` in `/itinerary/{date}` must equal `sum(activity.cost) * group_size`.
   - Adding an entry to a non-existent date should auto-create the `ItineraryDay`.
4. **Commands:**
   - Run backend: `uvicorn app.main:app --reload`
   - Run tests: `pytest`

## File Structure
- `app/` (FastAPI backend & SQLite DB)
- `mcp-server/` (Weather integration MCP server)
- `frontend/` (Basic Web UI)
- `tests/` (Test suite)

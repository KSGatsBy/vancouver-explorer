# Vancouver Summer Explorer

An activity planner for a multi-week stay in Vancouver. Track candidate activities,
organise them into day-by-day itineraries, and get **per-activity** weather warnings —
each activity is checked against the forecast at *its own* coordinates, not a single
vague verdict for the whole city.

Weather comes from [Open-Meteo](https://open-meteo.com/) through a local STDIO
**MCP server**, with graceful fallback to a bundled cache when the network is down.

See [DESIGN.md](DESIGN.md) for the full design rationale and milestone plan.

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000/> — the frontend is served from the same origin as
the API. Interactive API docs are at <http://127.0.0.1:8000/docs>.

No API key is required. Open-Meteo is free and unauthenticated.

---

## Architecture

```
[Frontend (HTML/JS)] --> [FastAPI backend] --> [SQLite]
                                |
                                --> [MCP client] --> [MCP server (STDIO)] --> [Open-Meteo]
```

The FastAPI backend does not call Open-Meteo directly. `GET /itinerary/{date}/weather`
spawns the MCP server as a subprocess over STDIO and invokes its tools, which keeps the
weather integration behind the MCP boundary.

```
app/
├── main.py              # FastAPI entry point, CORS, static frontend mount
├── db.py                # SQLite connection + schema
├── models.py            # Pydantic request/response models
├── routers/             # activities.py, itinerary.py, budget.py
└── services/            # cost.py, tags.py, mcp_client.py
mcp-server/
├── server.py            # FastMCP tool registration (STDIO transport)
├── weather.py           # Open-Meteo client, backoff, cache fallback
├── db.py                # Read-only itinerary lookups for the MCP tools
└── cached_forecast.json # Seeded offline fallback data
frontend/index.html      # Single-page UI
tests/                   # pytest suite
```

---

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/activities` | List activities; `?tag=a,b` filters by OR logic |
| POST | `/activities` | Create an activity |
| PUT | `/activities/{id}` | Full-field overwrite |
| DELETE | `/activities/{id}` | Delete an activity **and its itinerary entries** |
| GET | `/itinerary/{date}` | A day's entries plus `total_cost` |
| GET | `/itinerary/{date}/weather` | Per-activity forecast + recommendation (via MCP) |
| POST | `/itinerary-entries` | Add an entry; auto-creates the day if missing |
| PATCH | `/itinerary-entries/{id}` | Set `notes` / `rating` after visiting |
| GET | `/budget/week/{start_date}` | Per-day + week totals for 7 days from `start_date` |
| GET | `/health` | Liveness check |

### Rules worth knowing

- Activities created without `lat`/`lng` default to Vancouver centre
  (`49.2827, -123.1207`). Supplying only one of the pair is a `422` — pass both or neither.
- `total_cost` is always `sum(activity.cost) × group_size`, rounded to 2 decimals.
  A `null` cost counts as `0`. `/budget/week/{start_date}` reuses the same helper, so
  the two endpoints can never disagree about a given day.
- `POST /itinerary-entries` auto-creates the `ItineraryDay` (with `group_size` 1).
- `/budget/week/{start_date}` always returns all 7 days, including empty ones with a
  zero total, so the caller can render a full week.

---

## MCP server

Two tools, both returning JSON strings:

| Tool | Arguments | Returns |
|---|---|---|
| `get_forecast` | `date`, `location` (`"lat,lng"` or `"Vancouver"`) | `condition`, `rain_probability`, `source` |
| `suggest_indoor_or_outdoor` | `date` | One recommendation per itinerary entry that day |

Run it standalone (it speaks STDIO, so it expects an MCP client on stdin/stdout):

```bash
python mcp-server/server.py
```

### The `source` field

Every forecast is tagged with how much to trust it:

| `source` | Meaning |
|---|---|
| `live` | Fetched from Open-Meteo just now |
| `cached` | Open-Meteo was unreachable; served from `cached_forecast.json` |
| `unavailable` | No live *and* no cached data for that date |

**`rain_probability` is a placeholder `0.0` when `source` is `unavailable`** — always
check `source` before presenting the number. The recommendation string degrades to
`"forecast unavailable — plan flexibly"` in that case, and a missing forecast for one
activity never fails the whole day.

### Resilience

- Transient failures (network errors, 5xx, 429) retry up to 3 times with exponential
  backoff (0.5s → 1.0s). Other 4xx responses fail fast rather than burning retries.
- Successful forecasts are memoised for 5 minutes per `(date, lat, lng)`, so a day with
  five activities at one location makes **one** upstream call, not five.

---

## Configuration

All optional; sensible defaults apply.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `./vancouver_explorer.db` | SQLite file location |
| `ALLOWED_ORIGINS` | localhost `:8000` / `:5173` | Comma-separated CORS allowlist |
| `WEATHER_OFFLINE` | unset | Set to `1` to skip Open-Meteo entirely and use the bundled cache |

---

## Demo: the magic moment

`WEATHER_OFFLINE=1` makes the demo deterministic — it pins the forecast to the seeded
80%-rain entry instead of whatever the real weather happens to be:

```bash
WEATHER_OFFLINE=1 uvicorn app.main:app --reload
```

```bash
# 1. An outdoor activity with its own coordinates
curl -X POST localhost:8000/activities -H 'Content-Type: application/json' -d '{
  "name": "Capilano Suspension Bridge", "location": "North Vancouver",
  "cost": 65.0, "tags": ["outdoor"], "is_outdoor": true,
  "lat": 49.3427, "lng": -123.1147
}'

# 2. Put it on a day
curl -X POST localhost:8000/itinerary-entries -H 'Content-Type: application/json' -d '{
  "date": "2026-08-01", "activity_id": 1, "notes": "bring the camera"
}'

# 3. Ask what the weather means for it
curl localhost:8000/itinerary/2026-08-01/weather
```

```json
[{"activity_id": 1, "name": "Capilano Suspension Bridge",
  "rain_probability": 0.8, "recommendation": "indoor alternative suggested",
  "condition": "rainy", "source": "cached"}]
```

> **Note on the demo date.** `2026-08-01` is hardcoded in the seeded cache. Open-Meteo
> only serves a ~16-day forecast window, so once that date is in the past a *live* run
> falls back to the cache automatically. Tests are unaffected (they mock the HTTP layer
> or use the cache), but if you want a live demo, pick a near-future date.

---

## Testing

```bash
pytest
```

The suite covers activity CRUD and tag OR-logic, cost/budget arithmetic, itinerary
auto-creation, and both weather paths. Three tests spawn the **real MCP server
subprocess** over STDIO with `WEATHER_OFFLINE=1`, so the transport and tool
registration are genuinely exercised rather than mocked away.

Security scan (Semgrep is an optional dev dependency):

```bash
pip install -e ".[dev]"
semgrep --config=p/default --config=p/security-audit app mcp-server frontend tests
```

---

## Security notes

- Every SQL statement is a static string with bound parameters; no query is assembled
  at runtime. The week budget deliberately uses a `BETWEEN ? AND ?` range instead of a
  dynamically built `IN (?,?,?)` clause to keep it that way.
- All user-supplied values pass through an `esc()` helper before being interpolated
  into `innerHTML` in the frontend.
- CORS uses an explicit localhost allowlist. A `*` wildcard combined with
  `allow_credentials` is both unsafe and invalid under the CORS spec.
- No API keys anywhere — Open-Meteo needs none, and anything future belongs in an
  environment variable.

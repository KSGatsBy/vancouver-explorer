# Vancouver Summer Explorer - Design Document

## Overview

An activity planner for a 4-week stay in Vancouver. Users track candidate activities
(name, location, cost, tags), organize them into day-by-day itineraries, and get
automatic weather warnings — via an MCP server wrapping Open-Meteo — when a planned
outdoor activity collides with bad weather on that day.

## Demo Contract

- **Intended audience:** A visiting student/tourist doing a 4-week Vancouver stay who
  wants to plan a rain-safe Saturday without manually checking forecasts against a
  todo list of activities.
- **One-sentence problem:** People plan outdoor activities day by day but forget to
  cross-check them against the weather until it's too late to swap plans.
- **Magic moment:** Given a day's itinerary containing an outdoor activity (e.g.
  "Capilano Suspension Bridge" on 2026-08-01), the system checks that activity's
  lat/lng against the Open-Meteo forecast and returns a per-activity
  indoor/outdoor recommendation (e.g. "80% rain expected — consider an indoor
  alternative"), rather than a single vague day-level verdict.
- **Exact demo input → expected output:**
  - Input: `POST /itinerary-entries` with
    `{"date": "2026-08-01", "activity_id": 1, "notes": "bring the camera"}`
    where activity 1 = Capilano Suspension Bridge (`is_outdoor: true`).
  - Then call MCP tool `suggest_indoor_or_outdoor("2026-08-01")`.
  - Expected output: a list containing one entry for activity 1 with a rain
    probability and a recommendation string, e.g.
    `{"activity_id": 1, "name": "Capilano Suspension Bridge", "rain_probability": 0.8, "recommendation": "indoor alternative suggested"}`.
- **Three screens/states to show:**
  1. Empty state — activity list with an "Add Activity" form.
  2. Input state — a day itinerary being built (adding entries to 2026-08-01).
  3. Result state — the itinerary view for that day showing the weather warning
     next to the outdoor activity.
- **If the external API is unavailable:** `get_forecast` and
  `suggest_indoor_or_outdoor` fall back to a small cached/seeded forecast bundled
  with the MCP server, and the response is annotated with a friendly note (e.g.
  `"source": "cached"`) instead of failing the request.
- **Evidence the result is trustworthy:** An automated test seeds activity 1 with
  fixed lat/lng, mocks Open-Meteo to return a fixed 80% rain probability for
  2026-08-01, and asserts `suggest_indoor_or_outdoor` returns exactly that
  probability and a non-empty recommendation for that activity.

## Current Context

- **Problem:** Manually cross-referencing a day's planned activities against the
  weather forecast is easy to forget and doesn't account for different activities
  in the same day being in different parts of the city (and therefore under
  different forecasts).
- **Target users:** Someone on a multi-week Vancouver stay (student, intern, tourist)
  planning day trips and outdoor activities in advance.
- **Existing solutions and gaps:** Generic weather apps show forecast by city/area
  but don't know what you've planned; generic todo/itinerary apps track activities
  but don't check weather. Neither combines a specific activity's location with a
  forecast to give a per-activity recommendation.

## Requirements

### Functional Requirements
- [x] CRUD for `Activity` (name, location, cost, tags, is_outdoor, lat/lng with
      Vancouver-center default when omitted). Deleting an activity also removes
      its itinerary entries (SQLite foreign keys are off by default, so the
      cascade is explicit).
- [x] `GET /activities?tag=a,b` filters by OR logic across comma-separated tags.
- [x] Build day itineraries: `POST /itinerary-entries` auto-creates the
      `ItineraryDay` if it doesn't exist yet.
- [x] `GET /itinerary/{date}` returns entries plus `total_cost` for that day
      (`sum(entry.activity.cost) * group_size`).
- [x] `PATCH /itinerary-entries/{id}` to add rating/notes after visiting.
- [x] MCP tool `get_forecast(date, location)` returning condition + rain probability.
- [x] MCP tool `suggest_indoor_or_outdoor(date)` returning a per-activity
      recommendation list for every entry on that date.
- [x] `GET /budget/week/{start_date}` returns per-day and whole-week cost totals
      (Phase 3, Should tier).

### Non-Functional Requirements
- **Performance:** Single-user local tool; no specific concurrency target beyond
  responsive local API calls (well under 1s for CRUD, a few seconds tolerated for
  live weather calls).
- **Security:** Parameterized SQL only, input validation on all POST/PUT/PATCH
  bodies, no hardcoded API keys (Open-Meteo needs none, but any future key goes in
  env vars).
- **Accessibility:** Not a primary concern for M1/M2 given this is a personal
  planning tool; basic semantic HTML for the simple frontend is enough.

## Design Decisions

### 1. Relational storage over document storage

**Decision:** Use SQLite with a normalized `Activity` / `ItineraryDay` /
`ItineraryEntry` schema because:
- The data is naturally 1-to-N-to-1 (a day has many entries, each entry points to
  one activity), which maps cleanly to foreign keys and JOINs.
- Ratings/notes belong to the *entry* (a specific visit), not the activity itself,
  since the same activity could be revisited.

**Alternatives considered:**
- Single JSON blob per day: rejected — makes tag filtering and per-activity
  weather lookups (`suggest_indoor_or_outdoor`) awkward to query.
- NoSQL document store: rejected — adds an unnecessary dependency for a
  small, clearly relational, local-first dataset.

### 2. MCP server wraps Open-Meteo directly (no API key)

**Decision:** Use Open-Meteo via a local STDIO MCP server because:
- No API key/signup needed, which keeps setup friction at zero.
- STDIO transport is simplest for a local single-user tool; no need for hosting
  an HTTP MCP server.

**Alternatives considered:**
- A paid weather API (e.g. OpenWeatherMap): rejected — adds key management for
  no functional gain at this scale.
- Fetching weather directly from FastAPI without MCP: rejected — the project
  requirement is specifically to demonstrate MCP integration.

## Technical Design

### System Architecture

```
[Frontend (simple HTML/JS)] --> [FastAPI backend] --> [SQLite]
                                        |
                                        --> [MCP Client] --> [MCP Server (STDIO)] --> [Open-Meteo API]
```

### Data Models

```python
activities = """
    CREATE TABLE activities (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        location TEXT NOT NULL,
        cost REAL,                  -- per person
        tags TEXT,                  -- JSON list, e.g. '["free","outdoor"]'
        is_outdoor BOOLEAN DEFAULT 0,
        lat REAL,                   -- resolved to Vancouver center if omitted
        lng REAL
    )
"""

itinerary_days = """
    CREATE TABLE itinerary_days (
        date TEXT PRIMARY KEY,      -- YYYY-MM-DD
        group_size INTEGER DEFAULT 1
    )
"""

itinerary_entries = """
    CREATE TABLE itinerary_entries (
        id INTEGER PRIMARY KEY,
        day_id TEXT REFERENCES itinerary_days(date),
        activity_id INTEGER REFERENCES activities(id),
        notes TEXT,
        rating INTEGER              -- 1-5, nullable
    )
"""
```

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /activities | List activities, optional `?tag=a,b` (OR logic) |
| POST | /activities | Create activity; defaults lat/lng to Vancouver center if omitted |
| PUT | /activities/{id} | Full-field overwrite of an activity |
| DELETE | /activities/{id} | Delete an activity |
| GET | /itinerary/{date} | Get a day's entries + computed `total_cost` |
| GET | /itinerary/{date}/weather | Per-activity forecast + recommendation (via MCP) |
| POST | /itinerary-entries | Add an entry; auto-creates the `ItineraryDay` if missing |
| PATCH | /itinerary-entries/{id} | Update `notes` / `rating` after visiting |
| GET | /budget/week/{start_date} | Per-day + week cost totals for 7 days from `start_date` |
| GET | /health | Liveness check |

### MCP Server Design

**External API:** Open-Meteo (weather forecasts, no API key required)

**Tools to expose:**
1. `get_forecast(date: str, location: str)` — Returns weather condition and rain
   probability for a date/location. Falls back to cached/seeded data if
   Open-Meteo is unreachable.
2. `suggest_indoor_or_outdoor(date: str)` — For every `ItineraryEntry` on that
   date, looks up its activity's own lat/lng, checks the forecast individually,
   and returns a list of per-activity recommendations (not one verdict for the
   whole day).

**Transport:** STDIO (local)

### File Structure

```
project/
├── app/
│   ├── main.py          # FastAPI entry point
│   ├── db.py            # Database layer
│   ├── routers/         # activities.py, itinerary.py
│   └── services/        # cost calculation, tag filtering
├── mcp-server/
│   └── server.py        # get_forecast, suggest_indoor_or_outdoor
├── frontend/
│   └── index.html       # activity list + itinerary view
├── tests/
│   └── test_*.py
├── CLAUDE.md
└── README.md
```

## Implementation Plan

### M1: Core Application (Data & CRUD)
- [x] Set up project structure and CLAUDE.md
- [x] Implement `activities`, `itinerary_days`, `itinerary_entries` schema
- [x] Implement Activity CRUD + tag filtering (OR logic)
- [x] Implement itinerary endpoints incl. auto-create day + `total_cost`
- [x] Basic frontend: activity list + day itinerary view
- [x] Initial tests (mocked weather where relevant), demo the magic moment mocked

### M2: MCP Weather Integration
- [x] Implement `get_forecast` and `suggest_indoor_or_outdoor` MCP tools
- [x] Wire real Open-Meteo calls with graceful fallback to cached data
      (retry with exponential backoff; `WEATHER_OFFLINE=1` forces the cached
      path for offline demos/tests; `source` is `live` / `cached` / `unavailable`)
- [x] Connect MCP client into itinerary view (`GET /itinerary/{date}/weather`,
      per-activity warnings rendered in `frontend/index.html`)
- [x] Expand test suite to cover live-vs-mocked weather paths, including
      end-to-end tests that spawn the real STDIO MCP server subprocess
- [x] Run Semgrep and fix findings (wildcard CORS → explicit local origins)

### Phase 3: Polish (Should/Could tier)
- [x] Budget totals per day/week (Should) — `GET /budget/week/{start_date}`
      plus a week table in the frontend
- [x] Polish UI, write docs, prepare demo — README.md added; frontend gained the
      tag filter, activity delete, and rating/notes editing that the API already
      supported but the UI could not reach
- [ ] ~~Map view of activities (Could)~~ — descoped
- [ ] ~~Group voting on activities (Could)~~ — descoped; needs new schema and
      endpoints, and sits furthest from the weather × itinerary demo contract

## Testing Strategy

### Unit Tests
- Activity CRUD (happy path + 404s)
- Tag filter OR-logic across comma-separated tags
- `total_cost` calculation (`sum(cost) * group_size`)
- Auto-creation of `ItineraryDay` on first entry for a date
- MCP tools with a mocked Open-Meteo response

### Integration Tests
- MCP server connected to main app: itinerary + weather end-to-end
- Full workflow: create activity → add to itinerary → check weather → rate after visiting

### Security Testing
- Run Semgrep on all code
- Check for SQL injection (parameterized queries only), XSS in frontend, hardcoded secrets
- Validate all POST/PUT/PATCH bodies

## Security Considerations

- [x] Input validation on all endpoints (required fields, types, date format)
- [x] No hardcoded API keys (Open-Meteo needs none; env vars for anything future)
- [x] SQL parameterized queries (no string concatenation). Every statement is a
      static string with bound parameters — the week budget uses a
      `BETWEEN ? AND ?` range rather than a dynamically built `IN` clause, so no
      query is assembled at runtime at all.
- [x] CORS configuration for local frontend access (explicit localhost allowlist,
      overridable via `ALLOWED_ORIGINS`; a `*` wildcard alongside
      `allow_credentials` is both unsafe and invalid per the CORS spec)
- [x] Exponential backoff + request de-duplication on Open-Meteo calls. Note this
      is backoff and a short-lived response memo, **not** a true rate limiter —
      there is no token bucket or QPS ceiling.
- [x] Output escaping in the frontend — all user-supplied values pass through
      `esc()` before being interpolated into `innerHTML`

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [MCP Server Quickstart](https://modelcontextprotocol.io/quickstart/server)
- [Semgrep Getting Started](https://semgrep.dev/docs/getting-started/)
- [Open-Meteo API](https://open-meteo.com/)

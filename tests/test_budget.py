from app.services.cost import week_dates


def _make_activity(client, name, cost):
    return client.post(
        "/activities",
        json={"name": name, "location": "Vancouver", "cost": cost},
    ).json()


def _set_group_size(date, group_size):
    from app.db import get_connection

    with get_connection() as conn:
        conn.execute(
            "UPDATE itinerary_days SET group_size = ? WHERE date = ?",
            (group_size, date),
        )
        conn.commit()


def test_week_dates_spans_seven_consecutive_days():
    dates = week_dates("2026-08-01")
    assert len(dates) == 7
    assert dates[0] == "2026-08-01"
    assert dates[-1] == "2026-08-07"


def test_week_dates_crosses_month_boundary():
    assert week_dates("2026-07-30")[:3] == ["2026-07-30", "2026-07-31", "2026-08-01"]


def test_empty_week_returns_seven_zero_days(client):
    body = client.get("/budget/week/2026-08-01").json()

    assert body["start_date"] == "2026-08-01"
    assert body["end_date"] == "2026-08-07"
    assert len(body["days"]) == 7
    assert body["total_cost"] == 0.0
    assert all(day["total_cost"] == 0.0 for day in body["days"])
    assert all(day["entry_count"] == 0 for day in body["days"])


def test_week_total_sums_days_and_respects_group_size(client):
    bridge = _make_activity(client, "Capilano Suspension Bridge", 65.0)
    museum = _make_activity(client, "Museum of Anthropology", 18.0)

    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-01", "activity_id": bridge["id"]},
    )
    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-03", "activity_id": museum["id"]},
    )
    _set_group_size("2026-08-03", 3)

    body = client.get("/budget/week/2026-08-01").json()
    by_date = {day["date"]: day for day in body["days"]}

    assert by_date["2026-08-01"]["total_cost"] == 65.0
    assert by_date["2026-08-01"]["entry_count"] == 1
    # 18.00 * 3 people
    assert by_date["2026-08-03"]["total_cost"] == 54.0
    assert by_date["2026-08-03"]["group_size"] == 3
    assert body["total_cost"] == 119.0


def test_week_day_total_matches_itinerary_endpoint(client):
    """The two endpoints must never disagree about a single day's cost."""
    bridge = _make_activity(client, "Capilano Suspension Bridge", 65.0)
    museum = _make_activity(client, "Museum of Anthropology", 18.5)
    for activity in (bridge, museum):
        client.post(
            "/itinerary-entries",
            json={"date": "2026-08-02", "activity_id": activity["id"]},
        )
    _set_group_size("2026-08-02", 2)

    day_total = client.get("/itinerary/2026-08-02").json()["total_cost"]
    week = client.get("/budget/week/2026-08-01").json()
    week_day = next(d for d in week["days"] if d["date"] == "2026-08-02")

    assert week_day["total_cost"] == day_total == 167.0


def test_week_excludes_days_outside_the_window(client):
    activity = _make_activity(client, "Grouse Mountain", 70.0)
    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-08", "activity_id": activity["id"]},
    )

    body = client.get("/budget/week/2026-08-01").json()

    assert body["total_cost"] == 0.0
    assert "2026-08-08" not in {day["date"] for day in body["days"]}


def test_activity_with_null_cost_counts_as_zero(client):
    free = client.post(
        "/activities",
        json={"name": "Stanley Park Seawall", "location": "Vancouver"},
    ).json()
    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-01", "activity_id": free["id"]},
    )

    body = client.get("/budget/week/2026-08-01").json()
    day = next(d for d in body["days"] if d["date"] == "2026-08-01")

    assert day["entry_count"] == 1
    assert day["total_cost"] == 0.0


def test_malformed_start_date_is_rejected(client):
    assert client.get("/budget/week/08-01-2026").status_code == 422
    assert client.get("/budget/week/2026-13-01").status_code == 422
    assert client.get("/budget/week/not-a-date").status_code == 422

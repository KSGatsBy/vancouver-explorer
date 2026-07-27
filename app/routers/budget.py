from fastapi import APIRouter, HTTPException

from app.db import get_connection
from app.models import BudgetDay, BudgetWeekResponse, validate_iso_date
from app.services.cost import compute_total_cost, week_dates

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/week/{start_date}", response_model=BudgetWeekResponse)
def get_week_budget(start_date: str):
    """Per-day and whole-week cost totals for the 7 days from `start_date`.

    Days with no itinerary are reported with a zero total rather than omitted,
    so the caller always gets a full week to render.
    """
    try:
        validate_iso_date(start_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    dates = week_dates(start_date)
    # The week is contiguous, so a bounded range beats a dynamic IN clause:
    # it keeps the SQL fully static, and ISO-8601 dates sort chronologically
    # as plain strings.
    window = (dates[0], dates[-1])

    with get_connection() as conn:
        day_rows = conn.execute(
            "SELECT date, group_size FROM itinerary_days WHERE date BETWEEN ? AND ?",
            window,
        ).fetchall()
        entry_rows = conn.execute(
            """
            SELECT e.day_id, a.cost
            FROM itinerary_entries e
            JOIN activities a ON a.id = e.activity_id
            WHERE e.day_id BETWEEN ? AND ?
            """,
            window,
        ).fetchall()

    group_sizes = {row["date"]: row["group_size"] for row in day_rows}
    costs_by_date: dict[str, list[float | None]] = {date: [] for date in dates}
    for row in entry_rows:
        # BETWEEN compares strings, so ignore anything that isn't one of the
        # seven dates we asked for.
        if row["day_id"] in costs_by_date:
            costs_by_date[row["day_id"]].append(row["cost"])

    days: list[BudgetDay] = []
    for date in dates:
        costs = costs_by_date[date]
        group_size = group_sizes.get(date, 1)
        days.append(
            BudgetDay(
                date=date,
                group_size=group_size,
                entry_count=len(costs),
                # Same helper as GET /itinerary/{date}, so the two always agree.
                total_cost=compute_total_cost(costs, group_size),
            )
        )

    return BudgetWeekResponse(
        start_date=dates[0],
        end_date=dates[-1],
        days=days,
        total_cost=round(sum(day.total_cost for day in days), 2),
    )

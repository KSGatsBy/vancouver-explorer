from datetime import date as date_type
from datetime import timedelta

WEEK_LENGTH = 7


def compute_total_cost(activity_costs: list[float | None], group_size: int) -> float:
    subtotal = sum(cost or 0.0 for cost in activity_costs)
    return round(subtotal * group_size, 2)


def week_dates(start_date: str, length: int = WEEK_LENGTH) -> list[str]:
    """Return `length` consecutive ISO dates beginning at `start_date`."""
    start = date_type.fromisoformat(start_date)
    return [(start + timedelta(days=offset)).isoformat() for offset in range(length)]

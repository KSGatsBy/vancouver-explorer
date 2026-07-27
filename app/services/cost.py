def compute_total_cost(activity_costs: list[float | None], group_size: int) -> float:
    subtotal = sum(cost or 0.0 for cost in activity_costs)
    return round(subtotal * group_size, 2)

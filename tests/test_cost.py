def test_compute_total_cost():
    from app.services.cost import compute_total_cost

    assert compute_total_cost([10.0, 20.0, None], 2) == 60.0
    assert compute_total_cost([], 1) == 0.0

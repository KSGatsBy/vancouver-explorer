def test_create_itinerary_entry_auto_creates_day(client):
    activity = client.post(
        "/activities",
        json={"name": "Stanley Park", "location": "Vancouver", "cost": 0},
    ).json()

    response = client.post(
        "/itinerary-entries",
        json={"date": "2026-08-01", "activity_id": activity["id"], "notes": "morning walk"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["activity"]["name"] == "Stanley Park"
    assert data["notes"] == "morning walk"


def test_get_itinerary_total_cost(client):
    a1 = client.post(
        "/activities",
        json={"name": "A", "location": "Vancouver", "cost": 10},
    ).json()
    a2 = client.post(
        "/activities",
        json={"name": "B", "location": "Vancouver", "cost": 20},
    ).json()

    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-02", "activity_id": a1["id"]},
    )
    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-02", "activity_id": a2["id"]},
    )

    response = client.get("/itinerary/2026-08-02")
    assert response.status_code == 200
    data = response.json()
    assert data["total_cost"] == 30.0
    assert len(data["entries"]) == 2


def test_patch_itinerary_entry(client):
    activity = client.post(
        "/activities",
        json={"name": "Museum", "location": "Vancouver", "cost": 15},
    ).json()
    entry = client.post(
        "/itinerary-entries",
        json={"date": "2026-08-03", "activity_id": activity["id"]},
    ).json()

    response = client.patch(
        f"/itinerary-entries/{entry['id']}",
        json={"rating": 5, "notes": "great exhibits"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["rating"] == 5
    assert data["notes"] == "great exhibits"


def test_get_itinerary_not_found(client):
    response = client.get("/itinerary/2026-12-25")
    assert response.status_code == 404


def test_patch_itinerary_day_group_size(client):
    a = client.post(
        "/activities",
        json={"name": "Science World", "location": "Vancouver", "cost": 30.0},
    ).json()
    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-04", "activity_id": a["id"]},
    )

    response = client.patch(
        "/itinerary/2026-08-04",
        json={"group_size": 3},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["group_size"] == 3
    assert data["total_cost"] == 90.0


def test_delete_itinerary_entry(client):
    a = client.post(
        "/activities",
        json={"name": "Beach", "location": "Kitsilano", "cost": 0},
    ).json()
    entry = client.post(
        "/itinerary-entries",
        json={"date": "2026-08-05", "activity_id": a["id"]},
    ).json()

    # Delete entry
    del_res = client.delete(f"/itinerary-entries/{entry['id']}")
    assert del_res.status_code == 204

    # Verify entry is removed from itinerary day
    get_res = client.get("/itinerary/2026-08-05")
    assert get_res.status_code == 200
    assert len(get_res.json()["entries"]) == 0

    # Verify original activity still exists in activities catalog
    act_res = client.get("/activities")
    assert any(act["id"] == a["id"] for act in act_res.json())


def test_smart_swap_itinerary(client):
    outdoor_act = client.post(
        "/activities",
        json={"name": "Suspension Bridge", "location": "North Van", "cost": 50, "is_outdoor": True},
    ).json()
    indoor_act = client.post(
        "/activities",
        json={"name": "Art Gallery", "location": "Downtown", "cost": 25, "is_outdoor": False},
    ).json()

    client.post(
        "/itinerary-entries",
        json={"date": "2026-08-06", "activity_id": outdoor_act["id"]},
    )

    swap_res = client.post("/itinerary/2026-08-06/smart-swap")
    assert swap_res.status_code == 200
    data = swap_res.json()
    assert "status" in data
    assert "transit_suggestion" in data
    assert "updated_itinerary" in data


def test_ai_plan_itinerary(client):
    client.post(
        "/activities",
        json={"name": "Stanley Park Hike", "location": "Vancouver", "cost": 0, "is_outdoor": True, "tags": ["outdoor", "hike"]},
    )
    client.post(
        "/activities",
        json={"name": "Vancouver Art Gallery", "location": "Downtown", "cost": 25, "is_outdoor": False, "tags": ["museum", "art"]},
    )

    res = client.post(
        "/itinerary/2026-08-07/ai-plan",
        json={"preference": "museum", "max_budget": 50.0},
    )
    assert res.status_code == 200
    data = res.json()
    assert "planning_summary" in data
    assert len(data["selected_activities"]) > 0
    assert len(data["updated_itinerary"]["entries"]) > 0





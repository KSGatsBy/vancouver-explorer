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

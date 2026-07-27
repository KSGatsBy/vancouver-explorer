from app.db import VANCOUVER_LAT, VANCOUVER_LNG


def test_create_activity_defaults_lat_lng(client):
    response = client.post(
        "/activities",
        json={
            "name": "Stanley Park",
            "location": "Vancouver",
            "cost": 0,
            "tags": ["free", "outdoor"],
            "is_outdoor": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["lat"] == VANCOUVER_LAT
    assert data["lng"] == VANCOUVER_LNG
    assert data["name"] == "Stanley Park"
    assert data["tags"] == ["free", "outdoor"]


def test_create_activity_with_explicit_coords(client):
    response = client.post(
        "/activities",
        json={
            "name": "Capilano Suspension Bridge",
            "location": "North Vancouver",
            "cost": 65.0,
            "tags": ["outdoor"],
            "is_outdoor": True,
            "lat": 49.3427,
            "lng": -123.1147,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["lat"] == 49.3427
    assert data["lng"] == -123.1147


def test_list_activities(client):
    client.post(
        "/activities",
        json={"name": "A", "location": "Vancouver", "tags": ["free"]},
    )
    client.post(
        "/activities",
        json={"name": "B", "location": "Vancouver", "tags": ["paid"]},
    )
    response = client.get("/activities")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_tag_filter_or_logic(client):
    client.post(
        "/activities",
        json={"name": "Free Park", "location": "Vancouver", "tags": ["free", "outdoor"]},
    )
    client.post(
        "/activities",
        json={"name": "Museum", "location": "Vancouver", "tags": ["indoor", "paid"]},
    )
    client.post(
        "/activities",
        json={"name": "Beach", "location": "Vancouver", "tags": ["outdoor"]},
    )

    response = client.get("/activities", params={"tag": "free,paid"})
    assert response.status_code == 200
    names = {a["name"] for a in response.json()}
    assert names == {"Free Park", "Museum"}


def test_update_activity(client):
    create = client.post(
        "/activities",
        json={"name": "Old Name", "location": "Vancouver"},
    )
    activity_id = create.json()["id"]

    response = client.put(
        f"/activities/{activity_id}",
        json={
            "name": "New Name",
            "location": "Burnaby",
            "cost": 10.0,
            "tags": ["updated"],
            "is_outdoor": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "New Name"
    assert data["location"] == "Burnaby"
    assert data["cost"] == 10.0
    assert data["tags"] == ["updated"]
    assert data["is_outdoor"] is True


def test_update_activity_not_found(client):
    response = client.put(
        "/activities/999",
        json={"name": "X", "location": "Y"},
    )
    assert response.status_code == 404


def test_delete_activity(client):
    create = client.post(
        "/activities",
        json={"name": "To Delete", "location": "Vancouver"},
    )
    activity_id = create.json()["id"]

    response = client.delete(f"/activities/{activity_id}")
    assert response.status_code == 204

    listing = client.get("/activities")
    assert listing.json() == []


def test_delete_activity_not_found(client):
    response = client.delete("/activities/999")
    assert response.status_code == 404

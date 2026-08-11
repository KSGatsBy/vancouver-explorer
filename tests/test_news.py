"""Tests for GET /api/news endpoint."""

def test_get_vancouver_news(client):
    response = client.get("/api/news")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    first_item = data[0]
    assert "title" in first_item
    assert "summary" in first_item
    assert "source" in first_item
    assert "url" in first_item
    assert "category" in first_item
    assert "published_at" in first_item

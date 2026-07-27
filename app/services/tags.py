from typing import Any


def filter_activities_by_tags(
    activities: list[dict[str, Any]], tags: list[str]
) -> list[dict[str, Any]]:
    """Return activities whose tags overlap any of the given tags (OR logic)."""
    if not tags:
        return activities
    tag_set = {t.strip().lower() for t in tags if t.strip()}
    if not tag_set:
        return activities
    return [
        activity
        for activity in activities
        if any(t.lower() in tag_set for t in activity.get("tags", []))
    ]

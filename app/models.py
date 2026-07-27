import re
from datetime import date as date_type

from pydantic import BaseModel, Field, field_validator

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ActivityCreate(BaseModel):
    name: str = Field(min_length=1)
    location: str = Field(min_length=1)
    cost: float | None = None
    tags: list[str] = Field(default_factory=list)
    is_outdoor: bool = False
    lat: float | None = None
    lng: float | None = None


class ActivityUpdate(BaseModel):
    name: str = Field(min_length=1)
    location: str = Field(min_length=1)
    cost: float | None = None
    tags: list[str] = Field(default_factory=list)
    is_outdoor: bool = False
    lat: float | None = None
    lng: float | None = None


class ActivityResponse(BaseModel):
    id: int
    name: str
    location: str
    cost: float | None
    tags: list[str]
    is_outdoor: bool
    lat: float
    lng: float


class ItineraryEntryCreate(BaseModel):
    date: str
    activity_id: int
    notes: str | None = None

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        if not DATE_PATTERN.match(value):
            raise ValueError("date must be YYYY-MM-DD")
        date_type.fromisoformat(value)
        return value


class ItineraryEntryPatch(BaseModel):
    notes: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class ItineraryEntryResponse(BaseModel):
    id: int
    activity_id: int
    activity: ActivityResponse
    notes: str | None
    rating: int | None


class ItineraryDayResponse(BaseModel):
    date: str
    group_size: int
    entries: list[ItineraryEntryResponse]
    total_cost: float


class WeatherSuggestion(BaseModel):
    activity_id: int
    name: str
    rain_probability: float
    recommendation: str
    # "live" | "cached" | "unavailable" — how much to trust rain_probability.
    condition: str = "unknown"
    source: str = "live"

import re
from datetime import date as date_type

from pydantic import BaseModel, Field, field_validator

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_iso_date(value: str) -> str:
    """Reject anything that isn't a real YYYY-MM-DD calendar date."""
    if not DATE_PATTERN.match(value):
        raise ValueError("date must be YYYY-MM-DD")
    date_type.fromisoformat(value)
    return value


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
        return validate_iso_date(value)


class ItineraryEntryPatch(BaseModel):
    notes: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)


class ItineraryEntryResponse(BaseModel):
    id: int
    activity_id: int
    activity: ActivityResponse
    notes: str | None
    rating: int | None


class ItineraryDayPatch(BaseModel):
    group_size: int = Field(ge=1)


class ItineraryDayResponse(BaseModel):
    date: str
    group_size: int
    entries: list[ItineraryEntryResponse]
    total_cost: float


class BudgetDay(BaseModel):
    date: str
    group_size: int
    entry_count: int
    total_cost: float


class BudgetWeekResponse(BaseModel):
    start_date: str
    end_date: str
    days: list[BudgetDay]
    total_cost: float


class WeatherSuggestion(BaseModel):
    activity_id: int
    name: str
    rain_probability: float
    recommendation: str
    uv_index: float = 5.0
    transit_advice: str = ""
    # "live" | "cached" | "unavailable" — how much to trust rain_probability.
    condition: str = "unknown"
    source: str = "live"


class AIPlanRequest(BaseModel):
    preference: str = "outdoor"
    max_budget: float = 100.0


class SmartSwapResult(BaseModel):
    id: int
    name: str
    tier_matched: str
    distance_km: float
    cost_difference: float


class SmartSwapResponse(BaseModel):
    status: str
    original_activity_id: int
    swapped_activity: SmartSwapResult | None = None
    swap_reason: str
    transit_suggestion: str
    updated_itinerary: ItineraryDayResponse | None = None


class AIPlanActivity(BaseModel):
    id: int
    name: str
    cost_per_person: float
    reason: str


class AIPlanResponse(BaseModel):
    selected_activities: list[AIPlanActivity]
    total_cost: float
    weather_risk_level: str
    planning_summary: str
    updated_itinerary: ItineraryDayResponse | None = None


class WeatherAdvisoryResponse(BaseModel):
    date: str
    rain_risk: bool = False
    uv_risk: bool = False
    high_risk_activity_ids: list[int] = Field(default_factory=list)
    recommendation: str
    transit_advice: str
    suggestions: list[WeatherSuggestion] = Field(default_factory=list)



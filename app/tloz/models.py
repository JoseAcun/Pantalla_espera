from datetime import datetime

from pydantic import BaseModel, Field


class TlozGameInput(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=160)
    twitch_category_id: str = Field(default="", max_length=32)
    chronology_order: int = Field(default=100, ge=1, le=10_000)
    era: str = Field(default="", max_length=80)
    timeline_branch: str = Field(default="", max_length=80)
    release_year: int | None = Field(default=None, ge=1980, le=2100)
    platform: str = Field(default="", max_length=80)
    layout_key: str = Field(default="16_9", pattern=r"^(16_9|4_3|handheld|ds|3ds)$")
    enabled: bool = True


class TlozGame(TlozGameInput):
    id: int


class TlozZoneInput(BaseModel):
    # Empty is kept for zones created by the first manual panel version.
    slug: str = Field(default="", max_length=80, pattern=r"^$|^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    name: str = Field(min_length=2, max_length=160)
    chronology_order: int = Field(default=100, ge=1, le=10_000)


class TlozZone(TlozZoneInput):
    id: int
    game_id: int


class TlozObjectiveInput(BaseModel):
    # Catalog imports always provide a slug; legacy/manual records may not.
    slug: str = Field(default="", max_length=80, pattern=r"^$|^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
    title: str = Field(min_length=2, max_length=255)
    kind: str = Field(default="required", pattern=r"^(required|optional)$")
    chronology_order: int = Field(default=100, ge=1, le=10_000)
    description: str = Field(default="", max_length=500)
    enabled: bool = True


class TlozObjective(TlozObjectiveInput):
    id: int
    zone_id: int
    completed_at: datetime | None = None


class TlozCurrentUpdate(BaseModel):
    console_name: str | None = Field(default=None, max_length=80)
    zone_id: int | None = Field(default=None, ge=1)
    objective_id: int | None = Field(default=None, ge=1)
    special_state: str | None = Field(default=None, max_length=80)
    complete_objective: bool = False


class TlozTimelineEntry(BaseModel):
    title: str
    era: str = ""
    timeline_branch: str = ""
    current: bool = False


class TlozPreviouslyEntry(BaseModel):
    text: str
    occurred_at: datetime | None = None


class TlozOverlayState(BaseModel):
    active: bool = False
    twitch_category_id: str = ""
    twitch_stream_id: str = ""
    game: TlozGame | None = None
    console_name: str = ""
    current_zone: TlozZone | None = None
    current_objective: TlozObjective | None = None
    special_state: str = ""
    timeline: list[TlozTimelineEntry] = Field(default_factory=list)
    previously: list[TlozPreviouslyEntry] = Field(default_factory=list)

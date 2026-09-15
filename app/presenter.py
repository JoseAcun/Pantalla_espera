"""Ephemeral control state for the standalone presenter Browser Source."""

import asyncio
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


PresenterModule = Literal["intro", "community", "tloz", "cta"]
CameraPosition = Literal["left", "right", "none"]


def _plain_text(value: str) -> str:
    """Keep remote copy safe to render with textContent in every client."""
    return " ".join(value.replace("\x00", " ").split())


class PresenterControl(BaseModel):
    """The active, non-persistent presenter direction sent to Browser Sources."""

    remote_active: bool = False
    active_module: PresenterModule = "intro"
    auto_rotate: bool = True
    camera: CameraPosition = "right"
    duration_seconds: int = Field(default=15, ge=5, le=60)
    channel_name: str = Field(default="", max_length=48)
    schedule: str = Field(default="", max_length=120)
    rotation_started_at: datetime | None = None

    @field_validator("channel_name", "schedule")
    @classmethod
    def sanitize_plain_text(cls, value: str) -> str:
        return _plain_text(value)


class PresenterControlUpdate(BaseModel):
    """Partial commands accepted from the tablet-sized administration surface."""

    active_module: PresenterModule | None = None
    auto_rotate: bool | None = None
    camera: CameraPosition | None = None
    duration_seconds: int | None = Field(default=None, ge=5, le=60)
    channel_name: str | None = Field(default=None, max_length=48)
    schedule: str | None = Field(default=None, max_length=120)

    @field_validator("channel_name", "schedule")
    @classmethod
    def sanitize_optional_plain_text(cls, value: str | None) -> str | None:
        return _plain_text(value) if value is not None else None


class PresenterControlStore:
    """Small process-local store; restarting the backend intentionally resets it."""

    _modules: tuple[PresenterModule, ...] = ("intro", "community", "tloz", "cta")

    def __init__(self) -> None:
        self._control = PresenterControl()
        self._lock = asyncio.Lock()

    async def get(self) -> PresenterControl:
        async with self._lock:
            return self._control.model_copy(deep=True)

    @classmethod
    def _module_now(cls, control: PresenterControl, now: datetime) -> PresenterModule:
        if not control.auto_rotate or not control.rotation_started_at:
            return control.active_module
        elapsed = max(0, (now - control.rotation_started_at).total_seconds())
        offset = int(elapsed // control.duration_seconds)
        start = cls._modules.index(control.active_module)
        return cls._modules[(start + offset) % len(cls._modules)]

    async def update(self, update: PresenterControlUpdate) -> PresenterControl:
        """Apply one command and rebase an active rotation before changing it."""
        now = datetime.now(timezone.utc)
        async with self._lock:
            values = self._control.model_dump()
            values["active_module"] = self._module_now(self._control, now)
            values.update(update.model_dump(exclude_unset=True))
            values["remote_active"] = True
            values["rotation_started_at"] = now if values["auto_rotate"] else None
            self._control = PresenterControl.model_validate(values)
            return self._control.model_copy(deep=True)

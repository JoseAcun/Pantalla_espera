"""Persistent, restart-safe observations of live Twitch broadcasts."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from app.models import StreamState


@dataclass(frozen=True)
class StreamSession:
    id: int
    twitch_stream_id: str


class AnalyticsRepository(Protocol):
    def get_or_create_stream_session(self, state: StreamState, observed_at: datetime) -> StreamSession: ...
    def close_open_sessions_for_broadcaster(self, broadcaster_id: str, ended_at: datetime) -> int: ...
    def last_viewer_snapshot_at(self, stream_session_id: int) -> datetime | None: ...
    def record_viewer_snapshot(self, stream_session_id: int, viewer_count: int, captured_at: datetime) -> None: ...
    def record_session_category(self, stream_session_id: int, category_id: str, category_name: str, observed_at: datetime, source: str) -> bool: ...


def persist_stream_observation(repository: AnalyticsRepository, state: StreamState, observed_at: datetime, snapshot_interval_seconds: int) -> StreamSession | None:
    """Apply the online/offline state machine using durable database state only."""
    if observed_at.tzinfo is None:
        raise ValueError("Las observaciones de stream deben estar en UTC con zona horaria.")
    observed_at = observed_at.astimezone(timezone.utc)
    if not state.is_live or not state.twitch_stream_id:
        if state.broadcaster_id:
            repository.close_open_sessions_for_broadcaster(state.broadcaster_id, observed_at)
        return None

    session = repository.get_or_create_stream_session(state, observed_at)
    last_snapshot = repository.last_viewer_snapshot_at(session.id)
    interval = timedelta(seconds=max(1, snapshot_interval_seconds))
    if last_snapshot is None or observed_at - last_snapshot >= interval:
        repository.record_viewer_snapshot(session.id, max(0, state.viewer_count), observed_at)
    if state.category_id:
        repository.record_session_category(session.id, state.category_id, state.category or state.game, observed_at, "helix")
    return session

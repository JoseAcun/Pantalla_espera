"""Optional MariaDB event persistence for restoring overlay data after restarts."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, MetaData, String, Table, Column, create_engine, desc, select
from sqlalchemy.exc import IntegrityError


metadata = MetaData()
events = Table(
    "twitch_events",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("message_id", String(64), nullable=False, unique=True),
    Column("event_type", String(64), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)),
)


class EventRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def save(self, message_id: str, event_type: str, payload: dict[str, Any], occurred_at: datetime) -> bool:
        """Return False for a duplicate EventSub delivery."""
        try:
            with self.engine.begin() as connection:
                connection.execute(events.insert().values(
                    message_id=message_id,
                    event_type=event_type,
                    payload=payload,
                    occurred_at=occurred_at,
                ))
            return True
        except IntegrityError:
            return False

    def latest_events(self) -> list[tuple[str, dict[str, Any], datetime]]:
        """Return the most recent stored event for every overlay-supported type."""
        result: list[tuple[str, dict[str, Any], datetime]] = []
        event_types = ("channel.follow", "channel.subscribe", "channel.cheer", "channel.raid")
        with self.engine.connect() as connection:
            for event_type in event_types:
                row = connection.execute(
                    select(events.c.event_type, events.c.payload, events.c.occurred_at)
                    .where(events.c.event_type == event_type)
                    .order_by(desc(events.c.occurred_at))
                    .limit(1)
                ).first()
                if row:
                    result.append((row.event_type, row.payload, row.occurred_at))
        return result

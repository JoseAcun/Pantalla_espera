"""MariaDB persistence for EventSub deliveries and normalized Twitch metrics."""

import hashlib
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Text, create_engine, desc, select, text
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from app.analytics import StreamSession
from app.models import StreamState


metadata = MetaData()
users = Table(
    "twitch_users", metadata,
    Column("twitch_user_id", String(32), primary_key=True),
    Column("login", String(255), nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
)
user_name_history = Table(
    "twitch_user_name_history", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("twitch_user_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("login", String(255), nullable=False),
    Column("display_name", String(255), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
)
events = Table(
    "twitch_events", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("message_id", String(64), nullable=False, unique=True),
    Column("event_type", String(64), nullable=False, index=True),
    Column("payload", JSON, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)),
)
follows = Table(
    "follows", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("event_message_id", String(64), ForeignKey("twitch_events.message_id"), nullable=False, unique=True),
    Column("follower_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("broadcaster_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("followed_at", DateTime(timezone=True), nullable=False),
)
subscription_events = Table(
    "subscription_events", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("event_message_id", String(64), ForeignKey("twitch_events.message_id"), nullable=False, unique=True),
    Column("subscriber_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("broadcaster_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("tier", String(4), nullable=False),
    Column("is_gift", Boolean, nullable=False, default=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
cheers = Table(
    "cheers", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("event_message_id", String(64), ForeignKey("twitch_events.message_id"), nullable=False, unique=True),
    Column("cheerer_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=True),
    Column("broadcaster_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("is_anonymous", Boolean, nullable=False, default=False),
    Column("bits", Integer, nullable=False),
    Column("message", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)
raids = Table(
    "raids", metadata,
    Column("id", BigInteger, primary_key=True),
    Column("event_message_id", String(64), ForeignKey("twitch_events.message_id"), nullable=False, unique=True),
    Column("from_broadcaster_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("to_broadcaster_id", String(32), ForeignKey("twitch_users.twitch_user_id"), nullable=False),
    Column("viewers", Integer, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
)


def _as_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return fallback


class EventRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def initialize(self) -> None:
        metadata.create_all(self.engine)

    def save(self, message_id: str, event_type: str, payload: dict[str, Any], occurred_at: datetime) -> bool:
        """Store a delivery once, then map overlay-supported events to metric tables."""
        try:
            with self.engine.begin() as connection:
                connection.execute(events.insert().values(
                    message_id=message_id, event_type=event_type, payload=payload, occurred_at=occurred_at,
                ))
                self._normalize_event(connection, message_id, event_type, payload, occurred_at)
            return True
        except IntegrityError as error:
            # EventSub can redeliver a notification. The unique raw message ID makes it idempotent.
            if "message_id" in str(error.orig).lower() or "duplicate" in str(error.orig).lower():
                return False
            raise

    def record_hydrated_follower(self, state: StreamState) -> bool:
        """Save the latest follower returned by Helix, even if it predates this container."""
        follower = state.last_follower
        if not (state.broadcaster_id and follower.user_id and follower.timestamp):
            return False
        occurred_at = _as_datetime(follower.timestamp, datetime.now(timezone.utc))
        fingerprint = f"{state.broadcaster_id}:{follower.user_id}:{occurred_at.isoformat()}"
        message_id = "helix-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:58]
        payload = {
            "user_id": follower.user_id, "user_login": follower.user_login, "user_name": follower.username,
            "broadcaster_user_id": state.broadcaster_id, "broadcaster_user_login": state.broadcaster_login,
            "broadcaster_user_name": state.streamer, "followed_at": occurred_at.isoformat(),
        }
        return self.save(message_id, "channel.follow", payload, occurred_at)

    def record_manual_subscription(self, state: StreamState, subscriber: dict[str, Any], tier: str) -> bool:
        """Record a manually confirmed subscriber, retaining its provenance in the raw event."""
        if not state.broadcaster_id or not subscriber.get("id"):
            raise ValueError("Falta la identidad del broadcaster o del suscriptor.")
        occurred_at = datetime.now(timezone.utc)
        fingerprint = f"manual-sub:{state.broadcaster_id}:{subscriber['id']}:{occurred_at.isoformat()}"
        message_id = "manual-" + hashlib.sha256(fingerprint.encode()).hexdigest()[:57]
        payload = {
            "user_id": subscriber["id"], "user_login": subscriber.get("login", ""),
            "user_name": subscriber.get("display_name", ""), "broadcaster_user_id": state.broadcaster_id,
            "broadcaster_user_login": state.broadcaster_login, "broadcaster_user_name": state.streamer,
            "tier": tier, "is_gift": False, "source": "manual",
        }
        return self.save(message_id, "channel.subscribe", payload, occurred_at)

    def get_or_create_stream_session(self, state: StreamState, observed_at: datetime) -> StreamSession:
        """Use Twitch's immutable live-stream ID as the durable session key."""
        if not (state.twitch_stream_id and state.broadcaster_id):
            raise ValueError("Una sesión requiere twitch_stream_id y broadcaster_id.")
        started_at = _as_datetime(state.stream_started_at, observed_at)
        with self.engine.begin() as connection:
            self._upsert_user(connection, state.broadcaster_id, state.broadcaster_login, state.streamer, observed_at)
            # Twitch allows one active stream per broadcaster. If the process
            # missed an offline poll, close the stale prior session before
            # accepting a new live-stream ID.
            connection.execute(text("""
                UPDATE stream_sessions SET ended_at = :observed_at
                WHERE broadcaster_id = :broadcaster_id AND twitch_stream_id <> :stream_id
                  AND ended_at IS NULL
            """), {"broadcaster_id": state.broadcaster_id, "stream_id": state.twitch_stream_id, "observed_at": observed_at})
            connection.execute(text("""
                INSERT INTO stream_sessions (twitch_stream_id, broadcaster_id, started_at, game_name, title)
                VALUES (:stream_id, :broadcaster_id, :started_at, :game_name, :title)
                ON DUPLICATE KEY UPDATE broadcaster_id = VALUES(broadcaster_id),
                    game_name = VALUES(game_name), title = VALUES(title)
            """), {
                "stream_id": state.twitch_stream_id, "broadcaster_id": state.broadcaster_id,
                "started_at": started_at, "game_name": state.category or state.game or "", "title": state.title or "",
            })
            row = connection.execute(text("""
                SELECT id, twitch_stream_id FROM stream_sessions WHERE twitch_stream_id = :stream_id
            """), {"stream_id": state.twitch_stream_id}).one()
        return StreamSession(id=int(row.id), twitch_stream_id=row.twitch_stream_id)

    def open_stream_session(self, twitch_stream_id: str) -> StreamSession | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT id, twitch_stream_id FROM stream_sessions
                WHERE twitch_stream_id = :stream_id AND ended_at IS NULL
            """), {"stream_id": twitch_stream_id}).first()
        return StreamSession(id=int(row.id), twitch_stream_id=row.twitch_stream_id) if row else None

    def close_stream_session(self, twitch_stream_id: str, ended_at: datetime) -> bool:
        with self.engine.begin() as connection:
            result = connection.execute(text("""
                UPDATE stream_sessions SET ended_at = :ended_at
                WHERE twitch_stream_id = :stream_id AND ended_at IS NULL
            """), {"stream_id": twitch_stream_id, "ended_at": ended_at})
        return result.rowcount > 0

    def close_open_sessions_for_broadcaster(self, broadcaster_id: str, ended_at: datetime) -> int:
        """Close any open session after Helix confirms the channel is offline."""
        with self.engine.begin() as connection:
            result = connection.execute(text("""
                UPDATE stream_sessions SET ended_at = :ended_at
                WHERE broadcaster_id = :broadcaster_id AND ended_at IS NULL
            """), {"broadcaster_id": broadcaster_id, "ended_at": ended_at})
        return int(result.rowcount)

    def last_viewer_snapshot_at(self, stream_session_id: int) -> datetime | None:
        with self.engine.connect() as connection:
            captured_at = connection.execute(text("""
                SELECT MAX(captured_at) FROM viewer_snapshots WHERE stream_session_id = :session_id
            """), {"session_id": stream_session_id}).scalar_one()
        if captured_at is None:
            return None
        # MariaDB DATETIME deliberately has no timezone; the schema contract is UTC.
        return captured_at.replace(tzinfo=timezone.utc) if captured_at.tzinfo is None else captured_at.astimezone(timezone.utc)

    def record_viewer_snapshot(self, stream_session_id: int, viewer_count: int, captured_at: datetime) -> None:
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO viewer_snapshots (stream_session_id, viewer_count, captured_at)
                VALUES (:session_id, :viewer_count, :captured_at)
            """), {"session_id": stream_session_id, "viewer_count": max(0, viewer_count), "captured_at": captured_at})

    def record_session_category(self, stream_session_id: int, category_id: str, category_name: str, observed_at: datetime, source: str) -> bool:
        """Store only actual category transitions within this specific live session."""
        if not category_id:
            return False
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO stream_categories (twitch_category_id, name, first_seen_at, last_seen_at)
                VALUES (:category_id, :name, :observed_at, :observed_at)
                ON DUPLICATE KEY UPDATE name = VALUES(name), last_seen_at = VALUES(last_seen_at)
            """), {"category_id": category_id, "name": category_name or "Uncategorized", "observed_at": observed_at})
            previous = connection.execute(text("""
                SELECT twitch_category_id FROM stream_category_history
                WHERE stream_session_id = :session_id
                ORDER BY observed_at DESC, id DESC LIMIT 1
            """), {"session_id": stream_session_id}).scalar_one_or_none()
            if previous == category_id:
                return False
            connection.execute(text("""
                INSERT INTO stream_category_history (stream_session_id, twitch_category_id, observed_at, source)
                VALUES (:session_id, :category_id, :observed_at, :source)
            """), {"session_id": stream_session_id, "category_id": category_id, "observed_at": observed_at, "source": source})
        return True

    def _upsert_user(self, connection: Any, user_id: str, login: str, display_name: str, observed_at: datetime) -> None:
        if not user_id:
            return
        login = login or display_name or user_id
        display_name = display_name or login
        existing = connection.execute(
            select(users.c.login, users.c.display_name).where(users.c.twitch_user_id == user_id)
        ).first()
        if existing and (existing.login != login or existing.display_name != display_name):
            connection.execute(user_name_history.insert().values(
                twitch_user_id=user_id, login=login, display_name=display_name, observed_at=observed_at,
            ))
        statement = mysql_insert(users).values(
            twitch_user_id=user_id, login=login, display_name=display_name,
            first_seen_at=observed_at, last_seen_at=observed_at,
        )
        connection.execute(statement.on_duplicate_key_update(
            login=statement.inserted.login, display_name=statement.inserted.display_name,
            last_seen_at=statement.inserted.last_seen_at,
        ))

    def _normalize_event(self, connection: Any, message_id: str, event_type: str, event: dict[str, Any], received_at: datetime) -> None:
        broadcaster_id = event.get("broadcaster_user_id", "")
        self._upsert_user(connection, broadcaster_id, event.get("broadcaster_user_login", ""), event.get("broadcaster_user_name", ""), received_at)
        if event_type == "channel.follow":
            followed_at = _as_datetime(event.get("followed_at"), received_at)
            self._upsert_user(connection, event["user_id"], event.get("user_login", ""), event.get("user_name", ""), followed_at)
            connection.execute(follows.insert().values(
                event_message_id=message_id, follower_id=event["user_id"], broadcaster_id=broadcaster_id, followed_at=followed_at,
            ))
        elif event_type == "channel.subscribe":
            self._upsert_user(connection, event["user_id"], event.get("user_login", ""), event.get("user_name", ""), received_at)
            connection.execute(subscription_events.insert().values(
                event_message_id=message_id, subscriber_id=event["user_id"], broadcaster_id=broadcaster_id,
                tier=event.get("tier", ""), is_gift=event.get("is_gift", False), occurred_at=received_at,
            ))
        elif event_type == "channel.cheer":
            cheerer_id = event.get("user_id") or None
            if cheerer_id:
                self._upsert_user(connection, cheerer_id, event.get("user_login", ""), event.get("user_name", ""), received_at)
            connection.execute(cheers.insert().values(
                event_message_id=message_id, cheerer_id=cheerer_id, broadcaster_id=broadcaster_id,
                is_anonymous=bool(event.get("is_anonymous", not cheerer_id)), bits=event.get("bits", 0),
                message=event.get("message", ""), occurred_at=received_at,
            ))
        elif event_type == "channel.raid":
            source_id, target_id = event["from_broadcaster_user_id"], event["to_broadcaster_user_id"]
            self._upsert_user(connection, source_id, event.get("from_broadcaster_user_login", ""), event.get("from_broadcaster_user_name", ""), received_at)
            self._upsert_user(connection, target_id, event.get("to_broadcaster_user_login", ""), event.get("to_broadcaster_user_name", ""), received_at)
            connection.execute(raids.insert().values(
                event_message_id=message_id, from_broadcaster_id=source_id, to_broadcaster_id=target_id,
                viewers=event.get("viewers", 0), occurred_at=received_at,
            ))

    def latest_events(self) -> list[tuple[str, dict[str, Any], datetime]]:
        """Return the most recent stored event for every overlay-supported type."""
        result: list[tuple[str, dict[str, Any], datetime]] = []
        event_types = ("channel.follow", "channel.subscribe", "channel.cheer", "channel.raid")
        with self.engine.connect() as connection:
            for event_type in event_types:
                row = connection.execute(
                    select(events.c.event_type, events.c.payload, events.c.occurred_at)
                    .where(events.c.event_type == event_type).order_by(desc(events.c.occurred_at)).limit(1)
                ).first()
                if row:
                    result.append((row.event_type, row.payload, row.occurred_at))
        return result

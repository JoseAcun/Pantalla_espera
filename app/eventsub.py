"""Twitch EventSub WebSocket consumer; independent from the local OBS WebSocket."""

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import websockets

from app.models import CheerEvent, FollowEvent, RaidEvent, StreamState, SubscriptionEvent
from app.database import EventRepository
from app.state import StreamStateStore
from app.twitch import TwitchClient, TwitchError

logger = logging.getLogger(__name__)
EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws"


class EventSubClient:
    def __init__(self, twitch: TwitchClient, state: StreamStateStore, publish: Callable[[dict], Awaitable[None]], repository: EventRepository | None = None, game_handler: Callable[[str, dict, str], Awaitable[None]] | None = None, state_handler: Callable[[StreamState], Awaitable[None]] | None = None) -> None:
        self.twitch, self.state, self.publish = twitch, state, publish
        self.repository = repository
        self.game_handler = game_handler
        self.state_handler = state_handler
        self.task: asyncio.Task | None = None
        self.connected = False
        self.subscribed_types: set[str] = set()

    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._run(), name="twitch-eventsub")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.connected = False

    async def _run(self) -> None:
        reconnect_url: str | None = None
        while True:
            try:
                url = reconnect_url or EVENTSUB_URL
                reconnect_url = None
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as socket:
                    welcome = json.loads(await socket.recv())
                    session_id = welcome["payload"]["session"]["id"]
                    if url == EVENTSUB_URL:
                        await self._subscribe(session_id)
                    self.connected = True
                    logger.info("EventSub WebSocket connected")
                    async for raw in socket:
                        message = json.loads(raw)
                        kind = message["metadata"]["message_type"]
                        if kind == "notification":
                            await self._handle(message)
                        elif kind == "session_reconnect":
                            reconnect_url = message["payload"]["session"]["reconnect_url"]
                            break
                        elif kind == "revocation":
                            logger.warning("EventSub subscription revoked: %s", message["payload"]["subscription"].get("status"))
            except asyncio.CancelledError:
                raise
            except (OSError, websockets.WebSocketException, TwitchError, KeyError, json.JSONDecodeError) as error:
                logger.warning("EventSub disconnected (%s); retrying in 5 seconds", error)
                await asyncio.sleep(5)
            finally:
                self.connected = False

    async def _subscribe(self, session_id: str) -> None:
        validation = await self.twitch.validate_or_refresh()
        broadcaster_id = self.twitch.settings.twitch_broadcaster_id or validation["user_id"]
        definitions = [
            ("channel.follow", "2", {"broadcaster_user_id": broadcaster_id, "moderator_user_id": broadcaster_id}),
            ("channel.subscribe", "1", {"broadcaster_user_id": broadcaster_id}),
            ("channel.cheer", "1", {"broadcaster_user_id": broadcaster_id}),
            ("channel.raid", "1", {"to_broadcaster_user_id": broadcaster_id}),
            ("channel.update", "2", {"broadcaster_user_id": broadcaster_id}),
        ]
        if "user:read:chat" in validation.get("scopes", []):
            definitions.append(("channel.chat.message", "1", {"broadcaster_user_id": broadcaster_id, "user_id": validation["user_id"]}))
        else:
            logger.warning("Chat RPG disabled until Twitch OAuth includes user:read:chat")
        for event_type, version, condition in definitions:
            logger.info("Creating EventSub subscription: %s", event_type)
            await self.twitch.create_eventsub_subscription(event_type, version, condition, session_id)
            self.subscribed_types.add(event_type)
            logger.info("EventSub subscription enabled: %s", event_type)

    async def _handle(self, message: dict) -> None:
        event_type = message["metadata"]["subscription_type"]
        event = message["payload"]["event"]
        now = datetime.now(timezone.utc)
        if event_type == "channel.chat.message":
            logger.info("Chat message received from %s: %s", event.get("chatter_user_login", "unknown"), event.get("message", {}).get("text", ""))
        if self.repository:
            is_new = await asyncio.to_thread(
                self.repository.save,
                message["metadata"]["message_id"],
                event_type,
                event,
                now,
            )
            if not is_new:
                return
        if self.game_handler:
            await self.game_handler(event_type, event, message["metadata"]["message_id"])
        changes, data = self._event_changes(event_type, event, now)
        if not changes:
            return
        stream_state = await self.state.update(**changes)
        await self.publish({"type": "event", "event": event_type.removeprefix("channel."), "data": data})
        await self.publish({"type": "stream_state", "data": stream_state.model_dump(mode="json")})
        if self.state_handler:
            await self.state_handler(stream_state)

    @staticmethod
    def _event_changes(event_type: str, event: dict, received_at: datetime) -> tuple[dict[str, object], dict[str, object]]:
        now = received_at.isoformat()
        changes: dict[str, object] = {}
        data: dict[str, object]
        if event_type == "channel.follow":
            data = {"user_id": event["user_id"], "user_login": event["user_login"], "username": event["user_name"], "timestamp": event["followed_at"]}
            changes["last_follower"] = FollowEvent(**data)
        elif event_type == "channel.subscribe":
            data = {"user_id": event["user_id"], "user_login": event["user_login"], "username": event["user_name"], "tier": event["tier"], "timestamp": now}
            changes["last_subscriber"] = SubscriptionEvent(**data)
        elif event_type == "channel.cheer":
            data = {"user_login": event.get("user_login") or "", "username": event.get("user_name") or "Anonymous", "bits": event["bits"], "message": event.get("message", ""), "timestamp": now}
            changes["last_cheer"] = CheerEvent(**data)
        elif event_type == "channel.raid":
            data = {"broadcaster_login": event["from_broadcaster_user_login"], "username": event["from_broadcaster_user_name"], "viewers": event["viewers"], "timestamp": now}
            changes["last_raid"] = RaidEvent(**data)
        elif event_type == "channel.update":
            data = {"title": event["title"], "category": event.get("category_name", "")}
            changes.update(title=event.get("title", ""), game=event.get("category_name", "NO GAME SELECTED"), category=event.get("category_name", ""), category_id=event.get("category_id", ""))
        else:
            return {}, {}
        return changes, data

    async def restore_from_repository(self) -> None:
        if not self.repository:
            return
        latest = await asyncio.to_thread(self.repository.latest_events)
        restored = await self.state.get()
        for event_type, event, occurred_at in latest:
            changes, _ = self._event_changes(event_type, event, occurred_at)
            restored = restored.model_copy(update=changes)
        await self.state.replace(restored)

"""Twitch EventSub WebSocket consumer; independent from the local OBS WebSocket."""

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

import websockets

from app.models import CheerEvent, FollowEvent, RaidEvent, StreamState, SubscriptionEvent
from app.state import StreamStateStore
from app.twitch import TwitchClient, TwitchError

logger = logging.getLogger(__name__)
EVENTSUB_URL = "wss://eventsub.wss.twitch.tv/ws"


class EventSubClient:
    def __init__(self, twitch: TwitchClient, state: StreamStateStore, publish: Callable[[dict], Awaitable[None]]) -> None:
        self.twitch, self.state, self.publish = twitch, state, publish
        self.task: asyncio.Task | None = None
        self.connected = False

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
        broadcaster_id = self.twitch.settings.twitch_broadcaster_id or (await self.twitch.validate_or_refresh())["user_id"]
        definitions = (
            ("channel.follow", "2", {"broadcaster_user_id": broadcaster_id, "moderator_user_id": broadcaster_id}),
            ("channel.subscribe", "1", {"broadcaster_user_id": broadcaster_id}),
            ("channel.cheer", "1", {"broadcaster_user_id": broadcaster_id}),
            ("channel.raid", "1", {"to_broadcaster_user_id": broadcaster_id}),
            ("channel.update", "2", {"broadcaster_user_id": broadcaster_id}),
        )
        for event_type, version, condition in definitions:
            await self.twitch.create_eventsub_subscription(event_type, version, condition, session_id)

    async def _handle(self, message: dict) -> None:
        event_type = message["metadata"]["subscription_type"]
        event = message["payload"]["event"]
        now = datetime.now(timezone.utc).isoformat()
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
            changes.update(game=event.get("category_name", "NO GAME SELECTED"), category=event.get("category_name", ""))
        else:
            return
        stream_state = await self.state.update(**changes)
        await self.publish({"type": "event", "event": event_type.removeprefix("channel."), "data": data})
        await self.publish({"type": "stream_state", "data": stream_state.model_dump(mode="json")})

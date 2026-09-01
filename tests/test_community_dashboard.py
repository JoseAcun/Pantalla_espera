"""Small contract tests that do not need a running MariaDB instance."""

import asyncio
import sys
import types
import unittest
from datetime import datetime, timezone

# The controller only needs the repository type for annotation/import purposes.
# Keeping the fake here lets the existing lightweight test environment validate
# its WebSocket behaviour without a MariaDB driver.
repository_stub = types.ModuleType("app.game.repository")
repository_stub.GameRepository = object
sys.modules.setdefault("app.game.repository", repository_stub)

from app.game.controller import GameController
from app.game.models import CommunityDashboard, PublicGameEvent


class JoinRepository:
    def __init__(self) -> None:
        self.calls = 0

    def register_player(self, actor):
        self.calls += 1
        profile = types.SimpleNamespace(display_name=actor.display_name, level=1)
        event = PublicGameEvent(
            id=1, event_type="player_joined", display_name=actor.display_name,
            title="NEW PLAYER INITIALIZED", detail="", occurred_at=datetime.now(timezone.utc),
        ) if self.calls == 1 else None
        return profile, self.calls == 1, event


class CommunityDashboardContractTests(unittest.TestCase):
    def test_public_contract_has_no_twitch_user_identifier(self) -> None:
        payload = CommunityDashboard(generated_at=datetime.now(timezone.utc)).model_dump(mode="json")
        self.assertEqual(payload, {"generated_at": payload["generated_at"], "quests": [], "user_log": [], "season": None})
        self.assertNotIn("twitch_user_id", payload)

    def test_join_publishes_one_public_event_and_refresh(self) -> None:
        published, replies = [], []

        async def publish(message):
            published.append(message)

        async def reply(message):
            replies.append(message)

        controller = GameController(JoinRepository(), publish, reply)
        event = {"chatter_user_id": "42", "chatter_user_login": "kernelcat", "chatter_user_name": "KERNELCAT", "message": {"text": "!join"}}
        asyncio.run(controller.handle_twitch_event("channel.chat.message", event, "message-1"))
        asyncio.run(controller.handle_twitch_event("channel.chat.message", event, "message-2"))

        self.assertEqual([message["type"] for message in published], ["game.community.event", "game.community.refresh"])
        self.assertEqual(published[0]["data"]["display_name"], "KERNELCAT")
        self.assertEqual(len(replies), 1)  # Chat replies remain rate-limited.

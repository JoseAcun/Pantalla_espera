"""Application layer: translates Twitch chat into persisted game commands."""

import time
from typing import Awaitable, Callable

from app.game.models import ChatActor, EncounterState
from app.game.repository import GameRepository
from app.game.service import parse_command


class GameController:
    def __init__(self, repository: GameRepository, publish: Callable[[dict], Awaitable[None]], reply: Callable[[str], Awaitable[None]]) -> None:
        self.repository = repository
        self.publish = publish
        self.reply = reply
        self.last_reply_at = 0.0

    async def handle_twitch_event(self, event_type: str, event: dict, message_id: str) -> None:
        if event_type == "channel.update":
            await self._thread(self.repository.record_category, event.get("category_id", ""), event.get("category_name", ""))
            return
        if event_type != "channel.chat.message":
            return
        command = parse_command(event.get("message", {}).get("text", ""))
        if not command:
            return
        name, _arguments = command
        actor = ChatActor(user_id=event["chatter_user_id"], login=event.get("chatter_user_login", ""), display_name=event.get("chatter_user_name", "Viewer"))
        if name == "join":
            profile, created = await self._thread(self.repository.register_player, actor)
            await self._respond(f"[GAME MASTER] {'Registro completado' if created else 'Perfil recuperado'}, {profile.display_name}. Nivel {profile.level}.")
        elif name in {"stats", "profile"}:
            profile = await self._thread(self.repository.player, actor.user_id)
            await self._respond(f"[GAME MASTER] {profile.display_name}: LV {profile.level} | XP {profile.xp} | CREDITS {profile.credits}." if profile else "[GAME MASTER] Usa !join para crear tu perfil.")
        elif name == "boss":
            state = await self._thread(self.repository.active_encounter)
            await self._respond(self._boss_text(state))
        elif name in {"attack", "defend", "heal"}:
            state = await self._thread(self.repository.active_encounter)
            if not state:
                await self._respond("[GAME MASTER] No hay un boss activo.")
                return
            response = await self._thread(self.repository.add_action, state.id, actor, name, message_id)
            await self._respond(f"[GAME MASTER] {actor.display_name}: {response}")

    async def tick(self) -> None:
        resolved = await self._thread(self.repository.resolve_due_encounter)
        if not resolved:
            return
        state, result = resolved
        await self.publish({"type": "game.encounter.round_resolved", "data": {"state": state.model_dump(mode="json"), **result}})
        await self.publish({"type": "game.encounter.state", "data": state.model_dump(mode="json")})
        await self._respond(f"[GAME MASTER] ROUND RESOLVED // boss -{result['attack_damage']} // party integrity {state.party_integrity}/{state.max_party_integrity}.")
        if state.status == "victory":
            await self._respond(f"[GAME MASTER] {state.boss_name} TERMINATED. Rewards distributed.")
        elif state.status == "defeat":
            await self._respond(f"[GAME MASTER] PARTY OFFLINE. {state.boss_name} persists for a later rematch.")

    @staticmethod
    def _boss_text(state: EncounterState | None) -> str:
        if not state:
            return "[GAME MASTER] No hay un boss activo."
        return f"[GAME MASTER] {state.boss_name}: {state.current_hp}/{state.max_hp} HP // PARTY {state.party_integrity}/{state.max_party_integrity} // ROUND {state.round_number}."

    async def _respond(self, message: str) -> None:
        # A command may be received frequently; one public response every 1.5 seconds is enough for the MVP.
        if time.monotonic() - self.last_reply_at < 1.5:
            return
        self.last_reply_at = time.monotonic()
        await self.reply(message[:500])

    @staticmethod
    async def _thread(callable, *args):
        import asyncio
        return await asyncio.to_thread(callable, *args)

"""Application layer: translates Twitch chat into persisted game commands."""

import time
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.game.models import ChatActor, EncounterState, QuestCompletion
from app.game.repository import GameRepository
from app.game.service import parse_command


class GameController:
    def __init__(self, repository: GameRepository, publish: Callable[[dict], Awaitable[None]], reply: Callable[[str], Awaitable[None]], category_id: Callable[[], Awaitable[str]] | None = None) -> None:
        self.repository = repository
        self.publish = publish
        self.reply = reply
        self.category_id = category_id
        self.last_reply_at = 0.0
        self.logs: deque[dict[str, str]] = deque(maxlen=200)

    async def handle_twitch_event(self, event_type: str, event: dict, message_id: str) -> None:
        if event_type == "channel.update":
            await self._thread(self.repository.record_category, event.get("category_id", ""), event.get("category_name", ""))
            return
        if event_type != "channel.chat.message":
            return
        actor = ChatActor(user_id=event["chatter_user_id"], login=event.get("chatter_user_login", ""), display_name=event.get("chatter_user_name", "Viewer"))
        category_id = await self.category_id() if self.category_id else ""
        command = parse_command(event.get("message", {}).get("text", ""))
        if not command:
            completed = await self._thread(self.repository.record_chat_activity, actor, message_id, category_id)
            if completed:
                await self._announce_completions(actor, completed)
            return
        name, _arguments = command
        result = "ignored"
        if name == "join":
            profile, created, public_event = await self._thread(self.repository.register_player, actor)
            result = "registered" if created else "profile restored"
            await self._respond(f"[GAME MASTER] {'Registro completado' if created else 'Perfil recuperado'}, {profile.display_name}. Nivel {profile.level}.")
            if public_event:
                await self._publish_community_events([public_event])
        elif name in {"stats", "profile"}:
            profile = await self._thread(self.repository.player, actor.user_id)
            result = "stats returned" if profile else "missing profile"
            await self._respond(
                f"[GAME MASTER] {profile.display_name}: LV {profile.level} | XP {profile.xp} "
                f"({profile.xp_in_level}/{profile.xp_to_next_level} NEXT) | CREDITS {profile.credits}."
                if profile else "[GAME MASTER] Usa !join para crear tu perfil."
            )
        elif name in {"missions", "mission", "quests", "quest"}:
            profile = await self._thread(self.repository.player, actor.user_id)
            if not profile:
                result = "missing profile"
                await self._respond("[GAME MASTER] Usa !join para crear tu perfil antes de ver misiones.")
            else:
                missions = await self._thread(self.repository.player_quests, actor.user_id, category_id)
                result = "missions returned"
                await self._respond(self._missions_text(profile.display_name, missions))
        elif name == "boss":
            state = await self._thread(self.repository.active_encounter)
            result = "boss state returned" if state else "no active boss"
            await self._respond(self._boss_text(state))
        elif name in {"attack", "defend", "heal"}:
            state = await self._thread(self.repository.active_encounter)
            if not state:
                self._log(actor, name, "no active boss")
                await self._respond("[GAME MASTER] No hay un boss activo.")
                return
            response = await self._thread(self.repository.add_action, state.id, actor, name, message_id)
            result = response
            if "registrado" in response:
                completed = await self._thread(self.repository.record_raid_action, actor, message_id, state.category_id)
                if completed:
                    await self._announce_completions(actor, completed)
            # Successful actions are visible in the admin log, not echoed into chat one by one.
            if "registrado" not in response:
                await self._respond(f"[GAME MASTER] {actor.display_name}: {response}")
        self._log(actor, name, result)

    async def tick(self) -> None:
        resolved = await self._thread(self.repository.resolve_due_encounter)
        if not resolved:
            return
        state, result = resolved
        await self.publish({"type": "game.encounter.round_resolved", "data": {"state": state.model_dump(mode="json"), **result}})
        await self.publish({"type": "game.encounter.state", "data": state.model_dump(mode="json")})
        suffix = " // VICTORY" if state.status == "victory" else " // PARTY OFFLINE" if state.status == "defeat" else ""
        next_intent = f" // NEXT: BOSS {state.boss_intent.upper()}" if state.status == "active" else ""
        await self._respond(f"[GAME MASTER] ROUND RESOLVED // boss -{result['attack_damage']} // party integrity {state.party_integrity}/{state.max_party_integrity}.{next_intent}{suffix}", priority=True)
        if state.status == "victory":
            return
        elif state.status == "defeat":
            return

    async def force_resolve(self) -> tuple[EncounterState, dict[str, int | str]] | None:
        resolved = await self._thread(self.repository.resolve_due_encounter, True)
        if resolved:
            state, result = resolved
            await self.publish({"type": "game.encounter.round_resolved", "data": {"state": state.model_dump(mode="json"), **result}})
            await self.publish({"type": "game.encounter.state", "data": state.model_dump(mode="json")})
        return resolved

    async def announce_encounter(self, state: EncounterState) -> None:
        await self._respond(f"[GAME MASTER] {state.boss_name} CONNECTED // ROUND 01 // BOSS PREPARING: {state.boss_intent.upper()}.", priority=True)

    def command_logs(self) -> list[dict[str, str]]:
        return list(self.logs)

    def _log(self, actor: ChatActor, command: str, result: str) -> None:
        self.logs.appendleft({"at": datetime.now(timezone.utc).isoformat(), "user": actor.display_name, "command": f"!{command}", "result": result})

    @staticmethod
    def _boss_text(state: EncounterState | None) -> str:
        if not state:
            return "[GAME MASTER] No hay un boss activo."
        return f"[GAME MASTER] {state.boss_name}: {state.current_hp}/{state.max_hp} HP // PARTY {state.party_integrity}/{state.max_party_integrity} // ROUND {state.round_number}."

    @staticmethod
    def _missions_text(display_name: str, missions: list) -> str:
        if not missions:
            return f"[GAME MASTER] {display_name}: no hay misiones activas para esta categoría."
        labels = {"chat_messages": "chat", "activity_windows": "ventanas", "stream_days": "directos", "raid_actions": "raids"}
        parts = []
        for mission in missions[:3]:
            state = "✓" if mission.completed else f"{mission.progress}/{mission.objective_target}"
            objective = mission.description or labels.get(mission.objective_type, "progreso")
            parts.append(f"{mission.cadence.upper()} {mission.name} {state}: {objective}")
        suffix = " // ".join(parts)
        return f"[GAME MASTER] {display_name} // {suffix}"[:500]

    async def _announce_completions(self, actor: ChatActor, completions: list[QuestCompletion]) -> None:
        rewards = []
        for completion in completions:
            item = f" + {completion.item_name}" if completion.item_name else ""
            rewards.append(f"{completion.name}: +{completion.xp} XP +{completion.credits} C{item}")
        await self._respond(f"[GAME MASTER] MISIÓN COMPLETADA // {actor.display_name} // {' // '.join(rewards)}", priority=True)
        public_events = [event for completion in completions for event in completion.public_events]
        if public_events:
            await self._publish_community_events(public_events)

    async def _publish_community_events(self, events: list) -> None:
        """Keep browser updates small: the BRB refetches the bounded snapshot."""
        for event in events:
            await self.publish({"type": "game.community.event", "data": event.model_dump(mode="json")})
        await self.publish({"type": "game.community.refresh", "data": {}})

    async def _respond(self, message: str, priority: bool = False) -> None:
        # Successful combat actions stay in the debug view. Public commands are rate-limited.
        if not priority and time.monotonic() - self.last_reply_at < 4:
            return
        self.last_reply_at = time.monotonic()
        await self.reply(message[:500])

    @staticmethod
    async def _thread(callable, *args):
        import asyncio
        return await asyncio.to_thread(callable, *args)

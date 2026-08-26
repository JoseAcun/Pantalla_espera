"""Rules for the first cooperative raid vertical slice."""

from collections import Counter
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.game.models import ChatActor, EncounterState, PlayerProfile


XP_PER_ACTION = 20
CREDITS_PER_ACTION = 8
ACTION_VALUES = {"attack": 24, "defend": 8, "heal": 10}


class GameError(RuntimeError):
    pass


def parse_command(text: str) -> tuple[str, list[str]] | None:
    parts = text.strip().lower().split()
    if not parts or not parts[0].startswith("!"):
        return None
    return parts[0][1:], parts[1:]


def resolve_round(state: EncounterState, actions: list[str], boss_damage: int, now: datetime) -> tuple[dict[str, int | str], EncounterState]:
    """Pure, deterministic rule. Persistence is deliberately outside this function."""
    counts = Counter(actions)
    attack_damage = counts["attack"] * ACTION_VALUES["attack"]
    defend_value = counts["defend"] * ACTION_VALUES["defend"]
    heal_value = counts["heal"] * ACTION_VALUES["heal"]
    current_hp = max(0, state.current_hp - attack_damage)
    integrity_after_heal = min(state.max_party_integrity, state.party_integrity + heal_value)
    integrity = max(0, integrity_after_heal - max(0, boss_damage - defend_value))
    status = "victory" if current_hp == 0 else "defeat" if integrity == 0 else "active"
    updated = state.model_copy(update={
        "current_hp": current_hp,
        "party_integrity": integrity,
        "status": status,
        "round_number": state.round_number + (1 if status == "active" else 0),
        "round_ends_at": now + timedelta(seconds=state.round_seconds),
    })
    result = {"attack_damage": attack_damage, "defend_value": defend_value, "heal_value": heal_value, "boss_damage": boss_damage, "status": status}
    return result, updated


def new_encounter(category_id: str, boss_name: str, max_hp: int, boss_damage: int, round_seconds: int, now: datetime) -> EncounterState:
    return EncounterState(
        id=str(uuid4()), category_id=category_id, boss_name=boss_name, max_hp=max_hp, current_hp=max_hp,
        max_party_integrity=1000, party_integrity=1000, round_number=1,
        round_seconds=round_seconds, boss_damage=boss_damage, round_ends_at=now + timedelta(seconds=round_seconds), status="active",
    )

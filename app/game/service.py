"""Rules for the first cooperative raid vertical slice."""

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from app.game.models import ChatActor, EncounterState, PlayerProfile


XP_PER_ACTION = 20
CREDITS_PER_ACTION = 8
ACTION_VALUES = {"attack": 24, "defend": 8, "heal": 10}
# Colombia does not observe daylight saving time.  A fixed offset also keeps the
# container independent from optional OS/Python tzdata packages.
GAME_TIMEZONE = timezone(timedelta(hours=-5), name="America/Bogota")


class GameError(RuntimeError):
    pass


def parse_command(text: str) -> tuple[str, list[str]] | None:
    parts = text.strip().lower().split()
    if not parts or not parts[0].startswith("!"):
        return None
    return parts[0][1:], parts[1:]


def quest_period_key(cadence: str, now: datetime) -> str:
    """Stable local period names so daily/weekly resets follow the stream's timezone."""
    local = now.astimezone(GAME_TIMEZONE)
    if cadence == "weekly":
        year, week, _ = local.isocalendar()
        return f"week:{year}-{week:02d}"
    return f"day:{local.date().isoformat()}"


def boss_intent(encounter_id: str, round_number: int) -> str:
    """Stable across restarts without adding mutable random-state storage."""
    roll = int(hashlib.sha256(f"{encounter_id}:{round_number}".encode()).hexdigest()[:8], 16) % 100
    return "defend" if roll < 30 else "attack"


def resolve_round(state: EncounterState, actions: list[str], boss_damage: int, now: datetime) -> tuple[dict[str, int | str], EncounterState]:
    """Pure, deterministic rule. Persistence is deliberately outside this function."""
    counts = Counter(actions)
    attack_damage = counts["attack"] * ACTION_VALUES["attack"]
    if state.boss_intent == "defend":
        attack_damage //= 2
    defend_value = counts["defend"] * ACTION_VALUES["defend"]
    heal_value = counts["heal"] * ACTION_VALUES["heal"]
    current_hp = max(0, state.current_hp - attack_damage)
    integrity_after_heal = min(state.max_party_integrity, state.party_integrity + heal_value)
    actual_boss_damage = boss_damage if state.boss_intent == "attack" else 0
    integrity = max(0, integrity_after_heal - max(0, actual_boss_damage - defend_value))
    status = "victory" if current_hp == 0 else "defeat" if integrity == 0 else "active"
    updated = state.model_copy(update={
        "current_hp": current_hp,
        "party_integrity": integrity,
        "status": status,
        "round_number": state.round_number + (1 if status == "active" else 0),
        "round_ends_at": now + timedelta(seconds=state.round_seconds),
    })
    result = {"attack_damage": attack_damage, "defend_value": defend_value, "heal_value": heal_value, "boss_damage": actual_boss_damage, "intent": state.boss_intent, "status": status}
    return result, updated


def new_encounter(category_id: str, boss_name: str, max_hp: int, boss_damage: int, round_seconds: int, party_integrity: int, now: datetime) -> EncounterState:
    return EncounterState(
        id=str(uuid4()), category_id=category_id, boss_name=boss_name, max_hp=max_hp, current_hp=max_hp,
        max_party_integrity=party_integrity, party_integrity=party_integrity, round_number=1,
        round_seconds=round_seconds, boss_damage=boss_damage, round_ends_at=now + timedelta(seconds=round_seconds), status="active",
    )

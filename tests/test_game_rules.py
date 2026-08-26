from datetime import datetime, timedelta, timezone
import unittest

from app.game.models import EncounterState
from app.game.service import ACTION_VALUES, resolve_round


def encounter() -> EncounterState:
    now = datetime.now(timezone.utc)
    return EncounterState(
        id="test", boss_name="Test.exe", max_hp=100, current_hp=100,
        max_party_integrity=100, party_integrity=100, round_number=1,
        round_seconds=15, boss_damage=20, round_ends_at=now + timedelta(seconds=15), status="active",
    )


class RaidRuleTests(unittest.TestCase):
    def test_attack_reduces_boss_hp(self) -> None:
        result, state = resolve_round(encounter(), ["attack"], 20, datetime.now(timezone.utc))
        self.assertEqual(result["attack_damage"], ACTION_VALUES["attack"])
        self.assertEqual(state.current_hp, 100 - ACTION_VALUES["attack"])
        self.assertEqual(state.party_integrity, 80)

    def test_defense_absorbs_boss_damage(self) -> None:
        _, state = resolve_round(encounter(), ["defend", "defend", "defend"], 20, datetime.now(timezone.utc))
        self.assertEqual(state.party_integrity, 100)

    def test_victory_has_priority_when_boss_reaches_zero(self) -> None:
        state = encounter().model_copy(update={"current_hp": ACTION_VALUES["attack"]})
        _, resolved = resolve_round(state, ["attack"], 999, datetime.now(timezone.utc))
        self.assertEqual(resolved.status, "victory")
        self.assertEqual(resolved.current_hp, 0)

    def test_defeat_when_party_integrity_reaches_zero(self) -> None:
        _, state = resolve_round(encounter(), [], 100, datetime.now(timezone.utc))
        self.assertEqual(state.status, "defeat")
        self.assertEqual(state.party_integrity, 0)

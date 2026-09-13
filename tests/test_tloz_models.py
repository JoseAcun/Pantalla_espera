import unittest

from pydantic import ValidationError

from app.tloz.models import TlozCurrentUpdate, TlozGameInput, TlozOverlayState


class TlozModelTests(unittest.TestCase):
    def test_game_accepts_only_the_supported_obs_layouts(self) -> None:
        self.assertEqual(TlozGameInput(slug="oracle-of-ages", title="Oracle of Ages", layout_key="handheld").layout_key, "handheld")
        with self.assertRaises(ValidationError):
            TlozGameInput(slug="oracle-of-ages", title="Oracle of Ages", layout_key="ultrawide")

    def test_current_update_keeps_manual_state_small_and_optional(self) -> None:
        update = TlozCurrentUpdate(console_name="Nintendo DS", zone_id=3, objective_id=9, special_state="Puzzle", complete_objective=True)
        self.assertEqual(update.console_name, "Nintendo DS")
        self.assertTrue(update.complete_objective)

    def test_unmapped_twitch_category_has_a_safe_inactive_public_state(self) -> None:
        state = TlozOverlayState(twitch_category_id="123")
        self.assertFalse(state.active)
        self.assertEqual(state.timeline, [])

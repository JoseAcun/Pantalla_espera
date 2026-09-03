import unittest
from decimal import Decimal

from app.game.progression import (
    ProgressionConfig,
    cumulative_xp_for_level,
    level_from_total_xp,
    xp_progress_in_level,
    xp_required_for_next_level,
)


class ProgressionTests(unittest.TestCase):
    def test_documented_first_level_requirements(self) -> None:
        self.assertEqual(
            [xp_required_for_next_level(level) for level in range(1, 10)],
            [100, 115, 130, 150, 175, 200, 230, 265, 305],
        )

    def test_exact_boundaries_derive_the_expected_level(self) -> None:
        self.assertEqual(level_from_total_xp(0), 1)
        self.assertEqual(level_from_total_xp(99), 1)
        self.assertEqual(level_from_total_xp(100), 2)
        self.assertEqual(level_from_total_xp(214), 2)
        self.assertEqual(level_from_total_xp(215), 3)
        self.assertEqual(level_from_total_xp(345), 4)

    def test_multi_level_jump_and_existing_player_recalculation(self) -> None:
        # A legacy player keeps total XP; only the cached level changes.
        self.assertEqual(level_from_total_xp(8_815), 20)
        self.assertEqual(cumulative_xp_for_level(20), 8_815)
        self.assertEqual(xp_progress_in_level(8_815), (0, 1_425))

    def test_custom_curve_is_explicit_and_rounds_to_the_configured_unit(self) -> None:
        config = ProgressionConfig(base_xp=80, growth=Decimal("1.20"), rounding=10)
        self.assertEqual(xp_required_for_next_level(1, config), 80)
        self.assertEqual(xp_required_for_next_level(2, config), 100)
        self.assertEqual(xp_required_for_next_level(3, config), 120)


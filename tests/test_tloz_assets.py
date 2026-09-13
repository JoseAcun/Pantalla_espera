import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TlozAssetTests(unittest.TestCase):
    def test_ds_layout_makes_bottom_screen_the_primary_gameplay_area(self) -> None:
        css = (ROOT / "app/static/tloz/styles.css").read_text(encoding="utf-8")
        self.assertIn(".layout-ds .gameplay", css)
        self.assertIn("bottom:6%", css)
        self.assertIn(".layout-ds .secondary", css)
        self.assertIn(".layout-ds .webcam", css)

    def test_starting_soon_and_brb_reuse_the_public_recap(self) -> None:
        self.assertIn("/api/tloz/current", (ROOT / "app/static/tloz/starting-soon.js").read_text(encoding="utf-8"))
        self.assertIn("PREVIOUSLY IN ZELDA", (ROOT / "app/static/brb/index.html").read_text(encoding="utf-8"))

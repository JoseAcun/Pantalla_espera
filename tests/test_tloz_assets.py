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

    def test_16_by_9_is_a_compact_transparent_layer_with_no_guides_or_timeline(self) -> None:
        css = (ROOT / "app/static/tloz/styles.css").read_text(encoding="utf-8")
        self.assertIn(".layout-16_9 .source-guide,.layout-16_9 .timeline{display:none}", css)
        self.assertNotIn(".layout-16_9 .gameplay{", css)
        self.assertNotIn(".layout-16_9 .webcam{", css)

    def test_16_by_9_supports_safe_corner_and_minimal_mode_query_parameters(self) -> None:
        javascript = (ROOT / "app/static/tloz/overlay.js").read_text(encoding="utf-8")
        css = (ROOT / "app/static/tloz/styles.css").read_text(encoding="utf-8")
        self.assertIn("'top-left','top-right','bottom-left','bottom-right'", javascript)
        self.assertIn("query.get('mode')==='minimal'", javascript)
        self.assertIn(".layout-16_9.position-top-left .status-card", css)
        self.assertIn(".layout-16_9.position-bottom-right .status-card", css)
        self.assertIn(".layout-16_9.mode-minimal", css)

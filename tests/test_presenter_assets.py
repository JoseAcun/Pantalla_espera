import unittest
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app.main import app, broadcast_presenter_control, require_admin_token
from app.presenter import PresenterControl, PresenterControlStore, PresenterControlUpdate


ROOT = Path(__file__).resolve().parents[1]


class PresenterAssetTests(unittest.TestCase):
    def test_presenter_route_is_registered(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertIn("/overlay/presenter", paths)
        self.assertIn("/admin/presenter", paths)
        self.assertIn("/api/presenter/control", paths)

    def test_presenter_is_a_self_contained_static_surface(self) -> None:
        html = (ROOT / "app/static/presenter/index.html").read_text(encoding="utf-8")
        self.assertIn("/static/presenter/styles.css", html)
        self.assertIn("/static/presenter/app.js", html)
        self.assertIn('class="camera-safe"', html)

    def test_tablet_admin_has_the_main_controls_without_obs_integration(self) -> None:
        html = (ROOT / "app/static/presenter/admin.html").read_text(encoding="utf-8")
        javascript = (ROOT / "app/static/presenter/admin.js").read_text(encoding="utf-8")
        self.assertIn('data-module="intro"', html)
        self.assertIn('data-module="cta"', html)
        self.assertIn('id="toggle-rotation"', html)
        self.assertIn('data-camera="left"', html)
        self.assertIn('type="range"', html)
        self.assertIn("/api/presenter/control", javascript)
        self.assertNotIn("obs-websocket", html + javascript)

    def test_presenter_reads_only_existing_public_sources(self) -> None:
        javascript = (ROOT / "app/static/presenter/app.js").read_text(encoding="utf-8")
        self.assertIn("/api/state", javascript)
        self.assertIn("/api/game/community-dashboard", javascript)
        self.assertIn("/api/tloz/current", javascript)
        self.assertIn("/ws/overlay", javascript)
        self.assertNotIn("localStorage", javascript)
        self.assertNotIn("sessionStorage", javascript)
        self.assertNotIn("method: 'POST'", javascript)
        self.assertNotIn("method: 'PUT'", javascript)
        self.assertNotIn("method: 'DELETE'", javascript)

    def test_presenter_supports_requested_modes_and_safe_camera_positions(self) -> None:
        javascript = (ROOT / "app/static/presenter/app.js").read_text(encoding="utf-8")
        self.assertIn("['left', 'right', 'none']", javascript)
        self.assertIn("query.get('mode') === 'chat' ? 'chat' : 'trailer'", javascript)
        self.assertIn("const localDurationMs = 15_000", javascript)
        self.assertIn("event.key === 'ArrowRight'", javascript)
        self.assertIn("/^[1-4]$/", javascript)

    def test_control_store_is_ephemeral_sanitized_and_rebases_rotation(self) -> None:
        async def exercise() -> None:
            store = PresenterControlStore()
            self.assertFalse((await store.get()).remote_active)
            control = await store.update(PresenterControlUpdate(
                active_module="tloz", auto_rotate=False, camera="left", duration_seconds=12,
                channel_name="  Canal\n  seguro ", schedule=" Próximo\t directo ",
            ))
            self.assertTrue(control.remote_active)
            self.assertEqual("tloz", control.active_module)
            self.assertFalse(control.auto_rotate)
            self.assertEqual("left", control.camera)
            self.assertEqual("Canal seguro", control.channel_name)
            self.assertEqual("Próximo directo", control.schedule)
            self.assertIsNone(control.rotation_started_at)
            rotating = await store.update(PresenterControlUpdate(auto_rotate=True))
            self.assertIsNotNone(rotating.rotation_started_at)

        asyncio.run(exercise())

    def test_admin_token_check_and_control_broadcast(self) -> None:
        request = Request({"type": "http", "headers": [(b"x-overlay-admin-token", b"correct")]} )
        with patch("app.main.get_settings", return_value=SimpleNamespace(overlay_admin_token="correct")):
            require_admin_token(request)
        with patch("app.main.get_settings", return_value=SimpleNamespace(overlay_admin_token="correct")):
            bad_request = Request({"type": "http", "headers": [(b"x-overlay-admin-token", b"wrong")]})
            with self.assertRaises(HTTPException) as raised:
                require_admin_token(bad_request)
        self.assertEqual(403, raised.exception.status_code)

        class Connections:
            def __init__(self) -> None:
                self.messages: list[dict] = []

            async def broadcast(self, message: dict) -> None:
                self.messages.append(message)

        async def exercise() -> None:
            connections = Connections()
            fake_app = SimpleNamespace(state=SimpleNamespace(connections=connections))
            control = PresenterControl(remote_active=True, active_module="community", auto_rotate=False)
            await broadcast_presenter_control(fake_app, control)
            self.assertEqual("presenter.control", connections.messages[0]["type"])
            self.assertEqual("community", connections.messages[0]["data"]["active_module"])

        asyncio.run(exercise())

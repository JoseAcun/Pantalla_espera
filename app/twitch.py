"""Server-side Twitch OAuth and Helix client. Secrets never leave this module."""

import asyncio
import json
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import Settings
from app.models import FollowEvent, StreamState

TOKEN_URL = "https://id.twitch.tv/oauth2/token"
AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
HELIX_URL = "https://api.twitch.tv/helix"
REQUIRED_SCOPES = ("moderator:read:followers", "channel:read:subscriptions", "bits:read")


class TwitchError(RuntimeError):
    pass


class TokenStore:
    """Small local store for tokens returned by OAuth; excluded from Git."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, tokens: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


class TwitchClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tokens = TokenStore(settings.twitch_token_file)

    def is_configured(self) -> bool:
        return bool(self.settings.twitch_client_id)

    def authorization_url(self, state: str) -> str:
        if not self.is_configured():
            raise TwitchError("Falta TWITCH_CLIENT_ID en .env.")
        query = urlencode({
            "client_id": self.settings.twitch_client_id,
            "redirect_uri": self.settings.twitch_redirect_uri,
            "response_type": "code",
            "scope": " ".join(REQUIRED_SCOPES),
            "state": state,
        })
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        return await self._token_request({
            "client_id": self.settings.twitch_client_id or "",
            "client_secret": self.settings.twitch_client_secret or "",
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.settings.twitch_redirect_uri,
        })

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(TOKEN_URL, data=data)
        if response.is_error:
            raise TwitchError(f"Twitch rechazó la solicitud de token ({response.status_code}).")
        tokens = response.json()
        self.tokens.save(tokens)
        return tokens

    async def start_device_authorization(self) -> dict[str, Any]:
        """OAuth flow for public desktop apps; it deliberately needs no secret."""
        if not self.settings.twitch_client_id:
            raise TwitchError("Falta TWITCH_CLIENT_ID en .env.")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post("https://id.twitch.tv/oauth2/device", data={
                "client_id": self.settings.twitch_client_id,
                "scopes": " ".join(REQUIRED_SCOPES),
            })
        if response.is_error:
            raise TwitchError(f"Twitch no pudo iniciar la autorización ({response.status_code}).")
        return response.json()

    async def exchange_device_code(self, device_code: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(TOKEN_URL, data={
                "client_id": self.settings.twitch_client_id or "",
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        detail = response.json().get("message", "sin detalle") if response.headers.get("content-type", "").startswith("application/json") else "respuesta no válida"
        if response.status_code == 400 and detail in {"authorization_pending", "slow_down"}:
            return None
        if response.is_error:
            raise TwitchError(f"Twitch no completó la autorización de dispositivo: {detail}.")
        tokens = response.json()
        self.tokens.save(tokens)
        return tokens

    def access_token(self) -> str | None:
        return self.tokens.load().get("access_token") or self.settings.twitch_access_token

    async def validate(self) -> dict[str, Any]:
        token = self.access_token()
        if not token:
            raise TwitchError("Aún no hay token: abre /auth/twitch/start para autorizar la aplicación.")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(VALIDATE_URL, headers={"Authorization": f"OAuth {token}"})
        if response.is_error:
            raise TwitchError("El token de Twitch no es válido o ha expirado. Autoriza la aplicación de nuevo.")
        return response.json()

    async def validate_or_refresh(self) -> dict[str, Any]:
        try:
            return await self.validate()
        except TwitchError:
            if not (self.tokens.load().get("refresh_token") or self.settings.twitch_refresh_token):
                raise
            await self.refresh()
            return await self.validate()

    async def refresh(self) -> dict[str, Any]:
        refresh_token = self.tokens.load().get("refresh_token") or self.settings.twitch_refresh_token
        if not refresh_token:
            raise TwitchError("No existe refresh token; vuelve a autorizar la aplicación.")
        return await self._token_request({
            "client_id": self.settings.twitch_client_id or "",
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            **({"client_secret": self.settings.twitch_client_secret} if self.settings.twitch_client_secret else {}),
        })

    async def hydrate_state(self) -> StreamState:
        validation = await self.validate_or_refresh()
        broadcaster_id = self.settings.twitch_broadcaster_id or validation["user_id"]
        headers = {"Client-Id": self.settings.twitch_client_id or "", "Authorization": f"Bearer {self.access_token()}"}
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            users, channels, streams, followers = await self._get_initial_resources(client, broadcaster_id)
        user = users[0] if users else {}
        channel = channels[0] if channels else {}
        stream = streams[0] if streams else {}
        follower = followers[0] if followers else {}
        return StreamState(
            broadcaster_id=broadcaster_id,
            broadcaster_login=user.get("login", ""),
            streamer=user.get("display_name", "STREAMER"),
            game=stream.get("game_name") or channel.get("game_name") or "NO GAME SELECTED",
            category=stream.get("game_name") or channel.get("game_name") or "",
            status=self.settings.overlay_status,
            episode=self.settings.overlay_episode,
            custom_message=self.settings.overlay_custom_message,
            is_live=bool(stream),
            viewer_count=stream.get("viewer_count", 0),
            stream_started_at=stream.get("started_at"),
            last_follower=FollowEvent(
                user_id=follower.get("user_id", ""),
                user_login=follower.get("user_login", ""),
                username=follower.get("user_name", "—"),
                timestamp=follower.get("followed_at"),
            ),
        )

    async def refresh_live_metrics(self, current: StreamState) -> StreamState:
        """Refresh data that changes during a broadcast without discarding EventSub state."""
        validation = await self.validate_or_refresh()
        broadcaster_id = self.settings.twitch_broadcaster_id or validation["user_id"]
        headers = {"Client-Id": self.settings.twitch_client_id or "", "Authorization": f"Bearer {self.access_token()}"}
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.get(f"{HELIX_URL}/streams", params={"user_id": broadcaster_id})
        if response.is_error:
            raise TwitchError(f"Helix rechazó /streams ({response.status_code}).")
        streams = response.json().get("data", [])
        stream = streams[0] if streams else {}
        return current.model_copy(update={
            "is_live": bool(stream),
            "viewer_count": stream.get("viewer_count", 0),
            "stream_started_at": stream.get("started_at"),
            "game": stream.get("game_name") or current.game,
            "category": stream.get("game_name") or current.category,
        })

    async def user_by_login(self, login: str) -> dict[str, Any]:
        """Look up public Twitch user data without exposing the access token to a browser."""
        await self.validate_or_refresh()
        headers = {"Client-Id": self.settings.twitch_client_id or "", "Authorization": f"Bearer {self.access_token()}"}
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.get(f"{HELIX_URL}/users", params={"login": login.strip().lstrip("@")})
        if response.is_error:
            raise TwitchError(f"Helix rechazó /users ({response.status_code}).")
        users = response.json().get("data", [])
        if not users:
            raise TwitchError("No encontré ningún usuario de Twitch con ese nick.")
        return users[0]

    async def create_eventsub_subscription(self, event_type: str, version: str, condition: dict[str, str], session_id: str) -> None:
        """Create an EventSub subscription tied to Twitch's EventSub WebSocket."""
        headers = {"Client-Id": self.settings.twitch_client_id or "", "Authorization": f"Bearer {self.access_token()}"}
        payload = {"type": event_type, "version": version, "condition": condition, "transport": {"method": "websocket", "session_id": session_id}}
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.post(f"{HELIX_URL}/eventsub/subscriptions", json=payload)
        if response.is_error:
            detail = response.json().get("message", "sin detalle")
            raise TwitchError(f"No se pudo suscribir a {event_type}: {detail}")

    async def _get_initial_resources(self, client: httpx.AsyncClient, broadcaster_id: str) -> tuple[list, list, list, list]:
        async def get(path: str, params: dict[str, str]) -> list:
            response = await client.get(f"{HELIX_URL}{path}", params=params)
            if response.is_error:
                try:
                    detail = response.json().get("message", "sin detalle")
                except ValueError:
                    detail = "respuesta no JSON"
                raise TwitchError(f"Helix rechazó {path} ({response.status_code}): {detail}")
            return response.json().get("data", [])
        users, channels, streams, followers = await asyncio.gather(
            get("/users", {"id": broadcaster_id}),
            get("/channels", {"broadcaster_id": broadcaster_id}),
            get("/streams", {"user_id": broadcaster_id}),
            get("/channels/followers", {"broadcaster_id": broadcaster_id, "first": "1"}),
        )
        return users, channels, streams, followers


def create_oauth_state() -> str:
    return secrets.token_urlsafe(32)

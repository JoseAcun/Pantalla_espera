import asyncio
import contextlib
import logging
import secrets
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import get_settings
from app.eventsub import EventSubClient
from app.database import EventRepository
from app.models import StreamState, SubscriptionEvent
from app.state import StreamStateStore
from app.twitch import TwitchClient, TwitchError, create_oauth_state
from app.websocket import OverlayConnections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ManualSubscriberRequest(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    tier: str = Field(default="1000", pattern=r"^(1000|2000|3000)$")


async def refresh_metrics_periodically(app: FastAPI) -> None:
    """Poll the small live-metrics subset of Helix once a minute."""
    while True:
        await asyncio.sleep(60)
        if not app.state.twitch.access_token():
            continue
        try:
            current = await app.state.stream_state.get()
            refreshed = await app.state.twitch.refresh_live_metrics(current)
            await app.state.stream_state.replace(refreshed)
            await app.state.connections.broadcast({"type": "stream_state", "data": refreshed.model_dump(mode="json")})
        except Exception as error:
            logger.warning("Could not refresh live metrics: %s", error)


async def persist_hydrated_follower(app: FastAPI, state: StreamState) -> None:
    """Helix supplies one existing follower at startup; persist it like an EventSub follow."""
    if app.state.repository:
        try:
            await asyncio.to_thread(app.state.repository.record_hydrated_follower, state)
        except Exception:
            logger.exception("Could not persist the follower recovered from Helix")


def require_admin_token(request: Request) -> None:
    expected = get_settings().overlay_admin_token
    supplied = request.headers.get("X-Overlay-Admin-Token", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Define OVERLAY_ADMIN_TOKEN antes de usar cambios manuales.")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="Token de administración inválido.")


def initial_state() -> StreamState:
    settings = get_settings()
    return StreamState(
        status=settings.overlay_status,
        episode=settings.overlay_episode,
        custom_message=settings.overlay_custom_message,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.stream_state = StreamStateStore(initial_state())
    app.state.connections = OverlayConnections()
    app.state.twitch = TwitchClient(get_settings())
    app.state.oauth_states = {}
    database_url = get_settings().database_url
    app.state.repository = EventRepository(database_url) if database_url else None
    if app.state.repository:
        await asyncio.to_thread(app.state.repository.initialize)
        logger.info("MariaDB event persistence enabled")
    app.state.eventsub = EventSubClient(app.state.twitch, app.state.stream_state, app.state.connections.broadcast, app.state.repository)
    if app.state.twitch.access_token():
        try:
            hydrated = await app.state.twitch.hydrate_state()
            await app.state.stream_state.replace(hydrated)
            await persist_hydrated_follower(app, hydrated)
            app.state.eventsub.start()
        except Exception as error:
            logger.warning("Could not restore Twitch state at startup: %s", error)
    await app.state.eventsub.restore_from_repository()
    app.state.metrics_task = asyncio.create_task(refresh_metrics_periodically(app), name="twitch-live-metrics")
    logger.info("Overlay backend started. Open /auth/twitch/start to connect Twitch.")
    yield
    app.state.metrics_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.metrics_task
    await app.state.eventsub.stop()


app = FastAPI(title="Twitch Stream Overlay", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state", response_model=StreamState)
async def get_state() -> StreamState:
    return await app.state.stream_state.get()


@app.get("/auth/twitch/start", include_in_schema=False)
async def twitch_auth_start(request: Request) -> Response:
    state = create_oauth_state()
    now = time.monotonic()
    request.app.state.oauth_states = {
        value: expires_at for value, expires_at in request.app.state.oauth_states.items() if expires_at > now
    }
    request.app.state.oauth_states[state] = now + 600
    try:
        if request.app.state.twitch.settings.twitch_client_secret:
            response = RedirectResponse(request.app.state.twitch.authorization_url(state))
            # OAuth returns to this same browser/host, so the state remains scoped to it.
            response.set_cookie("twitch_oauth_state", state, max_age=600, httponly=True, samesite="lax")
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
            return response
        device = await request.app.state.twitch.start_device_authorization()
        device["next_poll_at"] = time.monotonic() + int(device.get("interval", 5))
        request.app.state.device_authorization = device
        return HTMLResponse(f'''<!doctype html><title>Conectar Twitch</title><h1>Conectar Twitch</h1>
<p>Abre <a href="{device["verification_uri"]}" target="_blank">Twitch Activate</a> y escribe este código:</p>
<h2>{device["user_code"]}</h2><p id="status">Esperando autorización…</p>
<script>setInterval(async()=>{{let r=await fetch('/auth/twitch/poll');let j=await r.json();document.querySelector('#status').textContent=j.message;if(j.connected) location.href='/overlay/brb';}}, {int(device.get("interval", 5)) * 1000});</script>''')
    except TwitchError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/auth/twitch/poll")
async def twitch_auth_poll(request: Request) -> dict[str, object]:
    device = getattr(request.app.state, "device_authorization", None)
    if not device:
        raise HTTPException(status_code=400, detail="No hay una autorización de dispositivo activa.")
    try:
        if time.monotonic() < device["next_poll_at"]:
            return {"connected": False, "message": "Esperando autorización en Twitch…"}
        device["next_poll_at"] = time.monotonic() + int(device.get("interval", 5))
        tokens = await request.app.state.twitch.exchange_device_code(device["device_code"])
        if tokens is None:
            return {"connected": False, "message": "Esperando autorización en Twitch…"}
        stream_state = await request.app.state.twitch.hydrate_state()
        await request.app.state.stream_state.replace(stream_state)
        await persist_hydrated_follower(request.app, stream_state)
        await request.app.state.eventsub.restore_from_repository()
        await request.app.state.connections.broadcast({"type": "stream_state", "data": stream_state.model_dump(mode="json")})
        request.app.state.eventsub.start()
        request.app.state.device_authorization = None
        return {"connected": True, "message": "Twitch conectado."}
    except TwitchError as error:
        request.app.state.device_authorization = None
        return {"connected": False, "message": str(error)}


@app.get("/auth/twitch/callback", include_in_schema=False)
async def twitch_auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> HTMLResponse:
    if error:
        raise HTTPException(status_code=400, detail=f"Twitch rechazó la autorización: {error}")
    expected_state = request.cookies.get("twitch_oauth_state")
    state_expires_at = request.app.state.oauth_states.pop(state, 0) if state else 0
    valid_server_state = state_expires_at > time.monotonic()
    valid_cookie_state = bool(expected_state and state and state == expected_state)
    if not code or not state or not (valid_server_state or valid_cookie_state):
        raise HTTPException(status_code=400, detail="Respuesta OAuth inválida o expirada. Reinicia el flujo en /auth/twitch/start.")
    try:
        await request.app.state.twitch.exchange_code(code)
        stream_state = await request.app.state.twitch.hydrate_state()
        await request.app.state.stream_state.replace(stream_state)
        await persist_hydrated_follower(request.app, stream_state)
        await request.app.state.connections.broadcast({"type": "stream_state", "data": stream_state.model_dump(mode="json")})
        request.app.state.eventsub.start()
    except TwitchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        logger.exception("Fallo inesperado sincronizando Twitch después de OAuth")
        raise HTTPException(status_code=500, detail="Error interno al sincronizar Twitch; revisa la consola del backend.")
    response = HTMLResponse("<h1>Twitch conectado</h1><p>Ya puedes cerrar esta pestaña y volver a OBS.</p>")
    response.delete_cookie("twitch_oauth_state")
    return response


@app.get("/api/twitch/status")
async def twitch_status(request: Request) -> dict:
    client: TwitchClient = request.app.state.twitch
    if not client.is_configured():
        return {"connected": False, "reason": "Faltan credenciales de la aplicación en .env."}
    try:
        token = await client.validate_or_refresh()
    except TwitchError as error:
        return {"connected": False, "reason": str(error)}
    return {"connected": True, "eventsub_connected": request.app.state.eventsub.connected, "login": token["login"], "user_id": token["user_id"], "scopes": token.get("scopes", [])}


@app.get("/api/twitch/users/{login}")
async def twitch_user_lookup(login: str, request: Request) -> dict[str, str]:
    """Inspect the public Twitch profile resolved from a nick before adding it manually."""
    try:
        user = await request.app.state.twitch.user_by_login(login)
    except TwitchError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {key: str(user.get(key, "")) for key in ("id", "login", "display_name", "description", "profile_image_url", "created_at", "broadcaster_type")}


@app.post("/api/twitch/manual/subscriber", response_model=StreamState)
async def add_manual_subscriber(payload: ManualSubscriberRequest, request: Request) -> StreamState:
    """Save a manually confirmed latest subscriber after resolving their Twitch account."""
    require_admin_token(request)
    repository: EventRepository | None = request.app.state.repository
    if not repository:
        raise HTTPException(status_code=503, detail="DATABASE_URL no está configurada.")
    try:
        user = await request.app.state.twitch.user_by_login(payload.login)
        state = await request.app.state.stream_state.get()
        if not state.broadcaster_id:
            state = await request.app.state.twitch.hydrate_state()
            await request.app.state.stream_state.replace(state)
        await asyncio.to_thread(repository.record_manual_subscription, state, user, payload.tier)
    except (TwitchError, ValueError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    event = SubscriptionEvent(
        user_id=user["id"], user_login=user.get("login", ""), username=user.get("display_name", "—"), tier=payload.tier,
    )
    updated = await request.app.state.stream_state.update(last_subscriber=event)
    await request.app.state.connections.broadcast({"type": "event", "event": "subscribe", "data": event.model_dump(mode="json")})
    await request.app.state.connections.broadcast({"type": "stream_state", "data": updated.model_dump(mode="json")})
    return updated


@app.post("/api/twitch/sync", response_model=StreamState)
async def twitch_sync(request: Request) -> StreamState:
    try:
        state = await request.app.state.twitch.hydrate_state()
    except TwitchError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    await request.app.state.stream_state.replace(state)
    await persist_hydrated_follower(request.app, state)
    await request.app.state.connections.broadcast({"type": "stream_state", "data": state.model_dump(mode="json")})
    return state


@app.get("/overlay/brb", include_in_schema=False)
async def brb_overlay() -> FileResponse:
    return FileResponse("app/static/brb/index.html")


@app.get("/overlay/stream", include_in_schema=False)
async def stream_overlay() -> FileResponse:
    return FileResponse("app/static/brb/stream.html")


@app.websocket("/ws/overlay")
async def overlay_socket(websocket: WebSocket) -> None:
    connections: OverlayConnections = app.state.connections
    await connections.connect(websocket)
    try:
        state = await app.state.stream_state.get()
        await websocket.send_json({"type": "stream_state", "data": state.model_dump(mode="json")})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await connections.disconnect(websocket)

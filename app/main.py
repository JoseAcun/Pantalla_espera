import asyncio
import contextlib
import logging
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.analytics import persist_stream_observation
from app.config import get_settings
from app.eventsub import EventSubClient
from app.database import EventRepository
from app.game.controller import GameController
from app.game.models import (
    BossDefinitionInput,
    CategoryContent,
    CommunityDashboard,
    EncounterState,
    ItemDefinition,
    ItemDefinitionInput,
    QuestDefinition,
    QuestDefinitionInput,
    QuestDefinitionUpdate,
    Season,
    SeasonInput,
)
from app.game.repository import GameRepository
from app.game.progression import ProgressionConfig
from app.game.service import GameError
from app.models import StreamState, SubscriptionEvent
from app.pokemon import MAX_TEAM_SIZE, PokeApiClient, PokemonError, PokemonTeam, PokemonTeamStore
from app.state import StreamStateStore
from app.twitch import TwitchClient, TwitchError, create_oauth_state
from app.tloz.models import TlozCurrentUpdate, TlozGame, TlozGameInput, TlozObjective, TlozObjectiveInput, TlozOverlayState, TlozZone, TlozZoneInput
from app.tloz.repository import TlozRepository
from app.websocket import OverlayConnections

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


class ManualSubscriberRequest(BaseModel):
    login: str = Field(min_length=1, max_length=255)
    tier: str = Field(default="1000", pattern=r"^(1000|2000|3000)$")


class PokemonMemberRequest(BaseModel):
    pokemon: str = Field(min_length=1, max_length=100)
    nickname: str = Field(default="", max_length=32)


class CategorySettingRequest(BaseModel):
    theme_key: str = Field(default="stream_os_generic", min_length=2, max_length=64)
    enabled: bool = True


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
            await persist_stream_analytics(app, refreshed)
            await record_stream_category(app, refreshed, "poll")
            await app.state.connections.broadcast({"type": "stream_state", "data": refreshed.model_dump(mode="json")})
            await broadcast_tloz_state(app, refreshed)
        except Exception as error:
            logger.warning("Could not refresh live metrics: %s", error)


async def game_tick_periodically(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(1)
        controller: GameController | None = app.state.game_controller
        if controller:
            try:
                await controller.tick()
            except Exception:
                logger.exception("Could not resolve a game round")


async def persist_hydrated_follower(app: FastAPI, state: StreamState) -> None:
    """Helix supplies one existing follower at startup; persist it like an EventSub follow."""
    if app.state.repository:
        try:
            await asyncio.to_thread(app.state.repository.record_hydrated_follower, state)
        except Exception:
            logger.exception("Could not persist the follower recovered from Helix")


async def persist_stream_analytics(app: FastAPI, state: StreamState) -> None:
    """Persist the Helix-derived live state without ever blocking the overlay."""
    repository: EventRepository | None = app.state.repository
    if not repository:
        return
    try:
        await asyncio.to_thread(
            persist_stream_observation,
            repository,
            state,
            datetime.now(timezone.utc),
            get_settings().viewer_snapshot_interval_seconds,
        )
    except Exception:
        logger.exception("Could not persist stream session analytics")


async def record_stream_category(app: FastAPI, state: StreamState, source: str) -> None:
    if app.state.game_repository and state.category_id:
        try:
            await asyncio.to_thread(app.state.game_repository.record_category, state.category_id, state.category, source)
        except Exception:
            logger.exception("Could not persist the Twitch category")


async def tloz_state(app: FastAPI, state: StreamState | None = None) -> TlozOverlayState:
    """Resolve Zelda's active game exclusively from Twitch's current category."""
    current = state or await app.state.stream_state.get()
    repository: TlozRepository | None = app.state.tloz_repository
    if not repository:
        return TlozOverlayState(twitch_category_id=current.category_id, twitch_stream_id=current.twitch_stream_id)
    return await asyncio.to_thread(repository.current_state, current.category_id, current.twitch_stream_id)


async def broadcast_tloz_state(app: FastAPI, state: StreamState | None = None) -> None:
    try:
        payload = await tloz_state(app, state)
        await app.state.connections.broadcast({"type": "tloz.state", "data": payload.model_dump(mode="json")})
    except Exception:
        logger.exception("Could not refresh TLOZ overlay state")


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
    settings = get_settings()
    app.state.stream_state = StreamStateStore(initial_state())
    app.state.connections = OverlayConnections()
    app.state.twitch = TwitchClient(settings)
    app.state.pokemon_team = PokemonTeamStore(settings.pokemon_data_dir)
    await asyncio.to_thread(app.state.pokemon_team.initialize)
    app.state.pokemon_api = PokeApiClient(app.state.pokemon_team)
    app.state.oauth_states = {}
    database_url = settings.database_url
    app.state.repository = EventRepository(database_url) if database_url else None
    progression = ProgressionConfig(
        base_xp=settings.game_level_base_xp,
        growth=Decimal(str(settings.game_level_growth)),
        rounding=settings.game_level_rounding,
    )
    app.state.game_repository = GameRepository(database_url, progression) if database_url else None
    app.state.tloz_repository = TlozRepository(database_url) if database_url else None
    if app.state.repository:
        await asyncio.to_thread(app.state.repository.initialize)
        logger.info("MariaDB event persistence enabled")
    async def current_game_category() -> str:
        return (await app.state.stream_state.get()).category_id

    app.state.game_controller = GameController(app.state.game_repository, app.state.connections.broadcast, app.state.twitch.send_chat_message, current_game_category) if app.state.game_repository else None
    app.state.eventsub = EventSubClient(
        app.state.twitch, app.state.stream_state, app.state.connections.broadcast,
        app.state.repository, app.state.game_controller.handle_twitch_event if app.state.game_controller else None,
        lambda state: broadcast_tloz_state(app, state),
    )
    if app.state.twitch.access_token():
        try:
            hydrated = await app.state.twitch.hydrate_state()
            await app.state.stream_state.replace(hydrated)
            await persist_hydrated_follower(app, hydrated)
            await persist_stream_analytics(app, hydrated)
            await record_stream_category(app, hydrated, "startup")
            await broadcast_tloz_state(app, hydrated)
            app.state.eventsub.start()
        except Exception as error:
            logger.warning("Could not restore Twitch state at startup: %s", error)
    await app.state.eventsub.restore_from_repository()
    app.state.metrics_task = asyncio.create_task(refresh_metrics_periodically(app), name="twitch-live-metrics")
    app.state.game_task = asyncio.create_task(game_tick_periodically(app), name="stream-os-game")
    logger.info("Overlay backend started. Open /auth/twitch/start to connect Twitch.")
    yield
    app.state.metrics_task.cancel()
    app.state.game_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.metrics_task
    with contextlib.suppress(asyncio.CancelledError):
        await app.state.game_task
    await app.state.eventsub.stop()


app = FastAPI(title="Twitch Stream Overlay", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount(
    "/pokemon/sprites",
    StaticFiles(directory=str(Path(get_settings().pokemon_data_dir) / "pokemon-sprites"), check_dir=False),
    name="pokemon-sprites",
)


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
        await persist_stream_analytics(request.app, stream_state)
        await record_stream_category(request.app, stream_state, "oauth")
        await request.app.state.eventsub.restore_from_repository()
        await request.app.state.connections.broadcast({"type": "stream_state", "data": stream_state.model_dump(mode="json")})
        await broadcast_tloz_state(request.app, stream_state)
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
        await persist_stream_analytics(request.app, stream_state)
        await record_stream_category(request.app, stream_state, "oauth")
        await request.app.state.connections.broadcast({"type": "stream_state", "data": stream_state.model_dump(mode="json")})
        await broadcast_tloz_state(request.app, stream_state)
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
    scopes = token.get("scopes", [])
    return {
        "connected": True,
        "eventsub_connected": request.app.state.eventsub.connected,
        "eventsub_types": sorted(request.app.state.eventsub.subscribed_types),
        "chat_ready": "user:read:chat" in scopes and "channel.chat.message" in request.app.state.eventsub.subscribed_types,
        "login": token["login"], "user_id": token["user_id"], "scopes": scopes,
    }


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
    await persist_stream_analytics(request.app, state)
    await record_stream_category(request.app, state, "sync")
    await request.app.state.connections.broadcast({"type": "stream_state", "data": state.model_dump(mode="json")})
    await broadcast_tloz_state(request.app, state)
    return state


def game_repository_or_503(request: Request) -> GameRepository:
    repository: GameRepository | None = request.app.state.game_repository
    if not repository:
        raise HTTPException(status_code=503, detail="DATABASE_URL no está configurada para el RPG.")
    return repository


def tloz_repository_or_503(request: Request) -> TlozRepository:
    repository: TlozRepository | None = request.app.state.tloz_repository
    if not repository:
        raise HTTPException(status_code=503, detail="DATABASE_URL no está configurada para TLOZ.")
    return repository


@app.get("/api/game/encounter", response_model=EncounterState | None)
async def game_encounter(request: Request) -> EncounterState | None:
    return await asyncio.to_thread(game_repository_or_503(request).active_encounter)


@app.get("/api/game/community-dashboard", response_model=CommunityDashboard)
async def game_community_dashboard(request: Request) -> CommunityDashboard:
    """Public, bounded BRB data. It deliberately exposes no technical IDs."""
    state = await request.app.state.stream_state.get()
    return await asyncio.to_thread(game_repository_or_503(request).community_dashboard, state.category_id)


@app.get("/api/game/seasons", response_model=list[Season])
async def game_seasons(request: Request) -> list[Season]:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).seasons)


@app.post("/api/game/seasons", response_model=Season)
async def create_game_season(payload: SeasonInput, request: Request) -> Season:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(game_repository_or_503(request).create_season, payload)
    except GameError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.put("/api/game/seasons/{season_id}", response_model=Season)
async def update_game_season(season_id: int, payload: SeasonInput, request: Request) -> Season:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(game_repository_or_503(request).update_season, season_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404 if "no existe" in str(error) else 422, detail=str(error)) from error


@app.get("/api/game/categories", response_model=list[CategoryContent])
async def game_categories(request: Request) -> list[CategoryContent]:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).categories)


@app.put("/api/game/categories/{category_id}", response_model=CategoryContent)
async def save_game_category(category_id: str, payload: CategorySettingRequest, request: Request) -> CategoryContent:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).save_category_setting, category_id, payload.theme_key, payload.enabled)


@app.post("/api/game/encounter", response_model=EncounterState)
async def start_game_encounter(payload: BossDefinitionInput, request: Request) -> EncounterState:
    require_admin_token(request)
    state = await request.app.state.stream_state.get()
    category_id = payload.category_id if payload.category_id is not None else state.category_id
    try:
        encounter = await asyncio.to_thread(game_repository_or_503(request).start_encounter, category_id, payload.name, payload.max_hp, payload.base_party_damage, payload.round_seconds, payload.party_integrity)
    except GameError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await request.app.state.connections.broadcast({"type": "game.encounter.state", "data": encounter.model_dump(mode="json")})
    if request.app.state.game_controller:
        await request.app.state.game_controller.announce_encounter(encounter)
    return encounter


@app.post("/api/game/encounter/resolve", response_model=EncounterState | None)
async def resolve_game_encounter(request: Request) -> EncounterState | None:
    require_admin_token(request)
    controller: GameController | None = request.app.state.game_controller
    if not controller:
        game_repository_or_503(request)
        return None
    result = await controller.force_resolve()
    return result[0] if result else None


@app.delete("/api/game/encounter", response_model=EncounterState | None)
async def cancel_game_encounter(request: Request) -> EncounterState | None:
    require_admin_token(request)
    encounter = await asyncio.to_thread(game_repository_or_503(request).cancel_active_encounter)
    if encounter:
        await request.app.state.connections.broadcast({"type": "game.encounter.state", "data": encounter.model_dump(mode="json")})
    return encounter


@app.get("/api/game/debug/chat")
async def game_chat_debug(request: Request) -> list[dict[str, str]]:
    require_admin_token(request)
    controller: GameController | None = request.app.state.game_controller
    return controller.command_logs() if controller else []


@app.get("/api/game/items", response_model=list[ItemDefinition])
async def game_items(request: Request) -> list[ItemDefinition]:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).items)


@app.post("/api/game/items", response_model=ItemDefinition)
async def create_game_item(payload: ItemDefinitionInput, request: Request) -> ItemDefinition:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).create_item, payload)


@app.get("/api/game/quests", response_model=list[QuestDefinition])
async def game_quests(request: Request) -> list[QuestDefinition]:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).quests)


@app.post("/api/game/quests", response_model=QuestDefinition)
async def create_game_quest(payload: QuestDefinitionInput, request: Request) -> QuestDefinition:
    require_admin_token(request)
    return await asyncio.to_thread(game_repository_or_503(request).create_quest, payload)


@app.put("/api/game/quests/{quest_id}", response_model=QuestDefinition)
async def update_game_quest(quest_id: int, payload: QuestDefinitionUpdate, request: Request) -> QuestDefinition:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(game_repository_or_503(request).update_quest, quest_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/tloz/current", response_model=TlozOverlayState)
async def get_tloz_current(request: Request) -> TlozOverlayState:
    """Public Browser Source data. The selected game always comes from Twitch."""
    return await tloz_state(request.app)


@app.get("/api/tloz/games", response_model=list[TlozGame])
async def list_tloz_games(request: Request) -> list[TlozGame]:
    require_admin_token(request)
    return await asyncio.to_thread(tloz_repository_or_503(request).games)


@app.post("/api/tloz/games", response_model=TlozGame)
async def create_tloz_game(payload: TlozGameInput, request: Request) -> TlozGame:
    require_admin_token(request)
    try:
        game = await asyncio.to_thread(tloz_repository_or_503(request).create_game, payload)
    except GameError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    await broadcast_tloz_state(request.app)
    return game


@app.put("/api/tloz/games/{game_id}", response_model=TlozGame)
async def update_tloz_game(game_id: int, payload: TlozGameInput, request: Request) -> TlozGame:
    require_admin_token(request)
    try:
        game = await asyncio.to_thread(tloz_repository_or_503(request).update_game, game_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404 if "no existe" in str(error) else 422, detail=str(error)) from error
    await broadcast_tloz_state(request.app)
    return game


@app.get("/api/tloz/games/{game_id}/zones", response_model=list[TlozZone])
async def list_tloz_zones(game_id: int, request: Request) -> list[TlozZone]:
    require_admin_token(request)
    return await asyncio.to_thread(tloz_repository_or_503(request).zones, game_id)


@app.post("/api/tloz/games/{game_id}/zones", response_model=TlozZone)
async def create_tloz_zone(game_id: int, payload: TlozZoneInput, request: Request) -> TlozZone:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(tloz_repository_or_503(request).create_zone, game_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.put("/api/tloz/zones/{zone_id}", response_model=TlozZone)
async def update_tloz_zone(zone_id: int, payload: TlozZoneInput, request: Request) -> TlozZone:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(tloz_repository_or_503(request).update_zone, zone_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/tloz/games/{game_id}/objectives", response_model=list[TlozObjective])
async def list_tloz_objectives(game_id: int, request: Request) -> list[TlozObjective]:
    require_admin_token(request)
    return await asyncio.to_thread(tloz_repository_or_503(request).objectives, game_id)


@app.post("/api/tloz/zones/{zone_id}/objectives", response_model=TlozObjective)
async def create_tloz_objective(zone_id: int, payload: TlozObjectiveInput, request: Request) -> TlozObjective:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(tloz_repository_or_503(request).create_objective, zone_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.put("/api/tloz/objectives/{objective_id}", response_model=TlozObjective)
async def update_tloz_objective(objective_id: int, payload: TlozObjectiveInput, request: Request) -> TlozObjective:
    require_admin_token(request)
    try:
        return await asyncio.to_thread(tloz_repository_or_503(request).update_objective, objective_id, payload)
    except GameError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.put("/api/tloz/current", response_model=TlozOverlayState)
async def update_tloz_current(payload: TlozCurrentUpdate, request: Request) -> TlozOverlayState:
    require_admin_token(request)
    state = await request.app.state.stream_state.get()
    try:
        result = await asyncio.to_thread(tloz_repository_or_503(request).update_current, state.category_id, state.twitch_stream_id, payload)
    except GameError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    await request.app.state.connections.broadcast({"type": "tloz.state", "data": result.model_dump(mode="json")})
    return result


@app.get("/api/pokemon/team", response_model=PokemonTeam)
async def pokemon_team(request: Request) -> PokemonTeam:
    return await asyncio.to_thread(request.app.state.pokemon_team.get_team)


@app.get("/api/pokemon/search")
async def pokemon_search(request: Request, q: str = "") -> list[dict[str, str]]:
    require_admin_token(request)
    try:
        return await request.app.state.pokemon_api.search(q)
    except PokemonError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.put("/api/pokemon/team/{slot}", response_model=PokemonTeam)
async def save_pokemon_member(slot: int, payload: PokemonMemberRequest, request: Request) -> PokemonTeam:
    require_admin_token(request)
    if not 1 <= slot <= MAX_TEAM_SIZE:
        raise HTTPException(status_code=422, detail=f"El espacio debe estar entre 1 y {MAX_TEAM_SIZE}.")
    try:
        member = await request.app.state.pokemon_api.make_member(slot, payload.pokemon, payload.nickname)
        team = await asyncio.to_thread(request.app.state.pokemon_team.save_member, member)
    except PokemonError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    await request.app.state.connections.broadcast({"type": "pokemon_team", "data": team.model_dump(mode="json")})
    return team


@app.delete("/api/pokemon/team/{slot}", response_model=PokemonTeam)
async def delete_pokemon_member(slot: int, request: Request) -> PokemonTeam:
    require_admin_token(request)
    if not 1 <= slot <= MAX_TEAM_SIZE:
        raise HTTPException(status_code=422, detail=f"El espacio debe estar entre 1 y {MAX_TEAM_SIZE}.")
    team = await asyncio.to_thread(request.app.state.pokemon_team.clear_slot, slot)
    await request.app.state.connections.broadcast({"type": "pokemon_team", "data": team.model_dump(mode="json")})
    return team


@app.get("/overlay/brb", include_in_schema=False)
async def brb_overlay() -> FileResponse:
    return FileResponse("app/static/brb/index.html")


@app.get("/overlay/stream", include_in_schema=False)
async def stream_overlay() -> FileResponse:
    return FileResponse("app/static/brb/stream.html")


@app.get("/overlay/pokemon", include_in_schema=False)
async def pokemon_overlay() -> FileResponse:
    return FileResponse("app/static/pokemon/overlay.html")


@app.get("/admin/pokemon", include_in_schema=False)
async def pokemon_admin() -> FileResponse:
    return FileResponse("app/static/pokemon/admin.html")


@app.get("/overlay/game/boss", include_in_schema=False)
async def game_boss_overlay() -> FileResponse:
    return FileResponse("app/static/game/overlay.html")


@app.get("/admin/game", include_in_schema=False)
async def game_admin() -> FileResponse:
    return FileResponse("app/static/game/admin.html")


@app.get("/overlay/tloz", include_in_schema=False)
async def tloz_overlay() -> FileResponse:
    return FileResponse("app/static/tloz/overlay.html")


@app.get("/overlay/tloz/starting-soon", include_in_schema=False)
async def tloz_starting_soon_overlay() -> FileResponse:
    return FileResponse("app/static/tloz/starting-soon.html")


@app.get("/admin/tloz", include_in_schema=False)
async def tloz_admin() -> FileResponse:
    return FileResponse("app/static/tloz/admin.html")


@app.websocket("/ws/overlay")
async def overlay_socket(websocket: WebSocket) -> None:
    connections: OverlayConnections = app.state.connections
    await connections.connect(websocket)
    try:
        state = await app.state.stream_state.get()
        await websocket.send_json({"type": "stream_state", "data": state.model_dump(mode="json")})
        team = await asyncio.to_thread(websocket.app.state.pokemon_team.get_team)
        await websocket.send_json({"type": "pokemon_team", "data": team.model_dump(mode="json")})
        if websocket.app.state.game_repository:
            try:
                # The client fetches the bounded public snapshot; do not push a
                # ranking for every connection or any internal game data.
                await websocket.send_json({"type": "game.community.snapshot", "data": {}})
            except Exception:
                logger.exception("Could not initialize the community dashboard socket message")
        await websocket.send_json({"type": "tloz.state", "data": (await tloz_state(websocket.app, state)).model_dump(mode="json")})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await connections.disconnect(websocket)

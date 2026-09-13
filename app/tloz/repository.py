"""Small MariaDB repository for manual Zelda progress and persistent recap data."""

from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.game.service import GameError
from app.tloz.models import (
    TlozCurrentUpdate,
    TlozGame,
    TlozGameInput,
    TlozObjective,
    TlozObjectiveInput,
    TlozOverlayState,
    TlozPreviouslyEntry,
    TlozTimelineEntry,
    TlozZone,
    TlozZoneInput,
)


def _model(model_type: type[Any], row: Any) -> Any:
    return model_type(**dict(row._mapping))


class TlozRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    def games(self) -> list[TlozGame]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, slug, title, COALESCE(twitch_category_id, '') AS twitch_category_id,
                       chronology_order, era, timeline_branch, release_year, platform, layout_key, enabled
                FROM tloz_games ORDER BY chronology_order, title
            """)).all()
        return [_model(TlozGame, row) for row in rows]

    def create_game(self, payload: TlozGameInput) -> TlozGame:
        data = payload.model_dump()
        try:
            with self.engine.begin() as connection:
                result = connection.execute(text("""
                    INSERT INTO tloz_games (slug, title, twitch_category_id, chronology_order, era, timeline_branch, release_year, platform, layout_key, enabled)
                    VALUES (:slug, :title, NULLIF(:twitch_category_id, ''), :chronology_order, :era, :timeline_branch, :release_year, :platform, :layout_key, :enabled)
                """), data)
                row = self._game_row(connection, result.lastrowid)
        except IntegrityError as error:
            raise GameError("El slug o la categoría Twitch ya están asociados a otro juego.") from error
        return _model(TlozGame, row)

    def update_game(self, game_id: int, payload: TlozGameInput) -> TlozGame:
        try:
            with self.engine.begin() as connection:
                changed = connection.execute(text("""
                    UPDATE tloz_games SET slug=:slug, title=:title, twitch_category_id=NULLIF(:twitch_category_id, ''),
                        chronology_order=:chronology_order, era=:era, timeline_branch=:timeline_branch, release_year=:release_year,
                        platform=:platform, layout_key=:layout_key, enabled=:enabled WHERE id=:id
                """), {**payload.model_dump(), "id": game_id})
                if not changed.rowcount:
                    raise GameError("El juego ya no existe.")
                row = self._game_row(connection, game_id)
        except IntegrityError as error:
            raise GameError("El slug o la categoría Twitch ya están asociados a otro juego.") from error
        return _model(TlozGame, row)

    def zones(self, game_id: int) -> list[TlozZone]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, game_id, COALESCE(slug, '') AS slug, name, chronology_order FROM tloz_zones
                WHERE game_id=:game_id ORDER BY chronology_order, id
            """), {"game_id": game_id}).all()
        return [_model(TlozZone, row) for row in rows]

    def create_zone(self, game_id: int, payload: TlozZoneInput) -> TlozZone:
        with self.engine.begin() as connection:
            self._game_row(connection, game_id)
            result = connection.execute(text("""
                INSERT INTO tloz_zones (game_id, slug, name, chronology_order)
                VALUES (:game_id, NULLIF(:slug, ''), :name, :chronology_order)
            """), {**payload.model_dump(), "game_id": game_id})
            row = connection.execute(text("SELECT id, game_id, COALESCE(slug, '') AS slug, name, chronology_order FROM tloz_zones WHERE id=:id"), {"id": result.lastrowid}).one()
        return _model(TlozZone, row)

    def update_zone(self, zone_id: int, payload: TlozZoneInput) -> TlozZone:
        with self.engine.begin() as connection:
            changed = connection.execute(text("UPDATE tloz_zones SET slug=NULLIF(:slug, ''), name=:name, chronology_order=:chronology_order WHERE id=:id"), {**payload.model_dump(), "id": zone_id})
            if not changed.rowcount:
                raise GameError("La zona ya no existe.")
            row = connection.execute(text("SELECT id, game_id, COALESCE(slug, '') AS slug, name, chronology_order FROM tloz_zones WHERE id=:id"), {"id": zone_id}).one()
        return _model(TlozZone, row)

    def objectives(self, game_id: int, playthrough_id: int | None = None) -> list[TlozObjective]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT o.id, o.zone_id, COALESCE(o.slug, '') AS slug, o.title, o.kind, o.chronology_order, o.description, o.enabled,
                       p.completed_at
                FROM tloz_objectives o JOIN tloz_zones z ON z.id=o.zone_id
                LEFT JOIN tloz_objective_progress p ON p.objective_id=o.id AND p.playthrough_id=:playthrough_id
                WHERE z.game_id=:game_id ORDER BY z.chronology_order, o.chronology_order, o.id
            """), {"game_id": game_id, "playthrough_id": playthrough_id}).all()
        return [_model(TlozObjective, row) for row in rows]

    def create_objective(self, zone_id: int, payload: TlozObjectiveInput) -> TlozObjective:
        with self.engine.begin() as connection:
            zone = connection.execute(text("SELECT id FROM tloz_zones WHERE id=:id"), {"id": zone_id}).first()
            if not zone:
                raise GameError("La zona ya no existe.")
            result = connection.execute(text("""
                INSERT INTO tloz_objectives (zone_id, slug, title, kind, chronology_order, description, enabled)
                VALUES (:zone_id, NULLIF(:slug, ''), :title, :kind, :chronology_order, :description, :enabled)
            """), {**payload.model_dump(), "zone_id": zone_id})
            row = connection.execute(text("""
                SELECT id, zone_id, COALESCE(slug, '') AS slug, title, kind, chronology_order, description, enabled, NULL AS completed_at
                FROM tloz_objectives WHERE id=:id
            """), {"id": result.lastrowid}).one()
        return _model(TlozObjective, row)

    def update_objective(self, objective_id: int, payload: TlozObjectiveInput) -> TlozObjective:
        with self.engine.begin() as connection:
            changed = connection.execute(text("""
                UPDATE tloz_objectives SET slug=NULLIF(:slug, ''), title=:title, kind=:kind, chronology_order=:chronology_order,
                    description=:description, enabled=:enabled WHERE id=:id
            """), {**payload.model_dump(), "id": objective_id})
            if not changed.rowcount:
                raise GameError("El objetivo ya no existe.")
            row = connection.execute(text("""
                SELECT id, zone_id, COALESCE(slug, '') AS slug, title, kind, chronology_order, description, enabled, NULL AS completed_at
                FROM tloz_objectives WHERE id=:id
            """), {"id": objective_id}).one()
        return _model(TlozObjective, row)

    def current_state(self, twitch_category_id: str, twitch_stream_id: str = "") -> TlozOverlayState:
        with self.engine.connect() as connection:
            game = self._game_for_category(connection, twitch_category_id)
            if not game:
                return TlozOverlayState(twitch_category_id=twitch_category_id, twitch_stream_id=twitch_stream_id)
            playthrough = self._active_playthrough(connection, game.id)
            return self._overlay_state(connection, game, playthrough, twitch_category_id, twitch_stream_id)

    def update_current(self, twitch_category_id: str, twitch_stream_id: str, payload: TlozCurrentUpdate) -> TlozOverlayState:
        with self.engine.begin() as connection:
            game = self._game_for_category(connection, twitch_category_id)
            if not game:
                raise GameError("La categoría actual de Twitch no está vinculada a un juego TLOZ habilitado.")
            playthrough = self._active_playthrough(connection, game.id, lock=True)
            if not playthrough:
                created = connection.execute(text("""
                    INSERT INTO tloz_playthroughs (game_id, twitch_stream_id, console_name, special_state, started_at)
                    VALUES (:game_id, NULLIF(:stream_id, ''), '', '', UTC_TIMESTAMP(6))
                """), {"game_id": game.id, "stream_id": twitch_stream_id})
                playthrough = self._active_playthrough(connection, game.id, lock=True, playthrough_id=created.lastrowid)
                self._history(connection, created.lastrowid, "playthrough_started")
            pid = int(playthrough["id"])
            zone_id = payload.zone_id if payload.zone_id is not None else playthrough["current_zone_id"]
            # A manual zone change intentionally clears the prior zone's objective
            # unless the operator selects a replacement in the same save.
            objective_id = payload.objective_id if payload.objective_id is not None else (
                None if payload.zone_id is not None else playthrough["current_objective_id"]
            )
            if zone_id:
                self._assert_zone(connection, int(zone_id), game.id)
            if objective_id:
                objective_zone = self._assert_objective(connection, int(objective_id), game.id)
                if payload.zone_id is not None and int(payload.zone_id) != objective_zone:
                    raise GameError("El objetivo seleccionado no pertenece a esa zona.")
                zone_id = objective_zone
            old_zone, old_objective, old_special = playthrough["current_zone_id"], playthrough["current_objective_id"], playthrough["special_state"]
            console = playthrough["console_name"] if payload.console_name is None else payload.console_name.strip()
            special = old_special if payload.special_state is None else payload.special_state.strip()
            connection.execute(text("""
                UPDATE tloz_playthroughs SET twitch_stream_id=NULLIF(:stream_id, ''), console_name=:console,
                    special_state=:special, current_zone_id=:zone_id, current_objective_id=:objective_id, updated_at=UTC_TIMESTAMP(6)
                WHERE id=:id
            """), {"stream_id": twitch_stream_id, "console": console, "special": special, "zone_id": zone_id, "objective_id": objective_id, "id": pid})
            if zone_id and zone_id != old_zone:
                self._history(connection, pid, "zone_entered", zone_id=zone_id)
            if objective_id and objective_id != old_objective:
                self._history(connection, pid, "objective_selected", objective_id=objective_id)
            if special != old_special:
                self._history(connection, pid, "special_state_changed", special_state=special)
            if payload.complete_objective:
                if not objective_id:
                    raise GameError("Selecciona un objetivo antes de marcarlo como completado.")
                completion = connection.execute(text("""
                    INSERT INTO tloz_objective_progress (playthrough_id, objective_id, completed_at)
                    VALUES (:playthrough_id, :objective_id, UTC_TIMESTAMP(6))
                    ON DUPLICATE KEY UPDATE completed_at=COALESCE(completed_at, VALUES(completed_at))
                """), {"playthrough_id": pid, "objective_id": objective_id})
                if completion.rowcount:
                    self._history(connection, pid, "objective_completed", objective_id=objective_id)
            fresh = self._active_playthrough(connection, game.id, playthrough_id=pid)
            return self._overlay_state(connection, game, fresh, twitch_category_id, twitch_stream_id)

    def _game_row(self, connection: Any, game_id: int) -> Any:
        row = connection.execute(text("""
            SELECT id, slug, title, COALESCE(twitch_category_id, '') AS twitch_category_id,
                   chronology_order, era, timeline_branch, release_year, platform, layout_key, enabled
            FROM tloz_games WHERE id=:id
        """), {"id": game_id}).first()
        if not row:
            raise GameError("El juego ya no existe.")
        return row

    def _game_for_category(self, connection: Any, category_id: str) -> TlozGame | None:
        if not category_id:
            return None
        row = connection.execute(text("""
            SELECT id, slug, title, COALESCE(twitch_category_id, '') AS twitch_category_id,
                   chronology_order, era, timeline_branch, release_year, platform, layout_key, enabled
            FROM tloz_games WHERE twitch_category_id=:category_id AND enabled=TRUE
        """), {"category_id": category_id}).first()
        return _model(TlozGame, row) if row else None

    @staticmethod
    def _active_playthrough(connection: Any, game_id: int, lock: bool = False, playthrough_id: int | None = None) -> Any:
        suffix = " FOR UPDATE" if lock else ""
        if playthrough_id:
            return connection.execute(text(f"SELECT * FROM tloz_playthroughs WHERE id=:id{suffix}"), {"id": playthrough_id}).mappings().first()
        return connection.execute(text(f"""
            SELECT * FROM tloz_playthroughs WHERE game_id=:game_id AND active=TRUE
            ORDER BY updated_at DESC, id DESC LIMIT 1{suffix}
        """), {"game_id": game_id}).mappings().first()

    @staticmethod
    def _assert_zone(connection: Any, zone_id: int, game_id: int) -> None:
        if not connection.execute(text("SELECT id FROM tloz_zones WHERE id=:id AND game_id=:game_id"), {"id": zone_id, "game_id": game_id}).first():
            raise GameError("La zona no pertenece al juego actual.")

    @staticmethod
    def _assert_objective(connection: Any, objective_id: int, game_id: int) -> int:
        row = connection.execute(text("""
            SELECT o.zone_id FROM tloz_objectives o JOIN tloz_zones z ON z.id=o.zone_id
            WHERE o.id=:id AND z.game_id=:game_id
        """), {"id": objective_id, "game_id": game_id}).first()
        if not row:
            raise GameError("El objetivo no pertenece al juego actual.")
        return int(row.zone_id)

    @staticmethod
    def _history(connection: Any, playthrough_id: int, event_type: str, zone_id: int | None = None, objective_id: int | None = None, special_state: str = "") -> None:
        connection.execute(text("""
            INSERT INTO tloz_progress_events (playthrough_id, event_type, zone_id, objective_id, special_state, occurred_at)
            VALUES (:playthrough_id, :event_type, :zone_id, :objective_id, :special_state, UTC_TIMESTAMP(6))
        """), {"playthrough_id": playthrough_id, "event_type": event_type, "zone_id": zone_id, "objective_id": objective_id, "special_state": special_state})

    def _overlay_state(self, connection: Any, game: TlozGame, playthrough: Any, category_id: str, stream_id: str) -> TlozOverlayState:
        timeline_rows = connection.execute(text("""
            SELECT title, era, timeline_branch FROM tloz_games WHERE enabled=TRUE ORDER BY chronology_order, title
        """)).all()
        if not playthrough:
            return TlozOverlayState(active=True, twitch_category_id=category_id, twitch_stream_id=stream_id, game=game,
                timeline=[TlozTimelineEntry(title=row.title, era=row.era, timeline_branch=row.timeline_branch, current=row.title == game.title) for row in timeline_rows])
        zone = None
        if playthrough["current_zone_id"]:
            row = connection.execute(text("SELECT id, game_id, COALESCE(slug, '') AS slug, name, chronology_order FROM tloz_zones WHERE id=:id"), {"id": playthrough["current_zone_id"]}).first()
            zone = _model(TlozZone, row) if row else None
        objective = None
        if playthrough["current_objective_id"]:
            row = connection.execute(text("""
                SELECT o.id, o.zone_id, COALESCE(o.slug, '') AS slug, o.title, o.kind, o.chronology_order, o.description, o.enabled, p.completed_at
                FROM tloz_objectives o LEFT JOIN tloz_objective_progress p
                  ON p.objective_id=o.id AND p.playthrough_id=:playthrough_id WHERE o.id=:id
            """), {"id": playthrough["current_objective_id"], "playthrough_id": playthrough["id"]}).first()
            objective = _model(TlozObjective, row) if row else None
        events = connection.execute(text("""
            SELECT e.event_type, e.special_state, e.occurred_at, z.name AS zone_name, o.title AS objective_title
            FROM tloz_progress_events e LEFT JOIN tloz_zones z ON z.id=e.zone_id
            LEFT JOIN tloz_objectives o ON o.id=e.objective_id
            WHERE e.playthrough_id=:playthrough_id ORDER BY e.occurred_at DESC, e.id DESC LIMIT 6
        """), {"playthrough_id": playthrough["id"]}).all()
        labels = {"zone_entered": lambda row: f"Zona recorrida: {row.zone_name}", "objective_completed": lambda row: f"Objetivo completado: {row.objective_title}", "special_state_changed": lambda row: f"Situación: {row.special_state}", "objective_selected": lambda row: f"Objetivo actual: {row.objective_title}"}
        recap = [TlozPreviouslyEntry(text=labels[row.event_type](row), occurred_at=row.occurred_at) for row in events if row.event_type in labels and labels[row.event_type](row).rstrip(": ")]
        return TlozOverlayState(active=True, twitch_category_id=category_id, twitch_stream_id=stream_id, game=game,
            console_name=playthrough["console_name"], current_zone=zone, current_objective=objective,
            special_state=playthrough["special_state"], timeline=[TlozTimelineEntry(title=row.title, era=row.era, timeline_branch=row.timeline_branch, current=row.title == game.title) for row in timeline_rows], previously=recap)

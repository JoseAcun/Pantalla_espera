"""MariaDB adapter for the first STREAM_OS RPG slice."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.game.models import CategoryContent, ChatActor, EncounterState, ItemDefinition, ItemDefinitionInput, PlayerProfile
from app.game.service import CREDITS_PER_ACTION, XP_PER_ACTION, GameError, new_encounter, resolve_round


class GameRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    @staticmethod
    def _encounter(row: Any) -> EncounterState:
        return EncounterState(**dict(row._mapping))

    def record_category(self, category_id: str, name: str, source: str = "eventsub") -> None:
        if not category_id:
            return
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO stream_categories (twitch_category_id, name, first_seen_at, last_seen_at)
                VALUES (:id, :name, :now, :now)
                ON DUPLICATE KEY UPDATE name = VALUES(name), last_seen_at = VALUES(last_seen_at)
            """), {"id": category_id, "name": name or "Uncategorized", "now": now})
            connection.execute(text("""
                INSERT INTO stream_category_history (twitch_category_id, observed_at, source)
                VALUES (:id, :now, :source)
            """), {"id": category_id, "now": now, "source": source})

    def categories(self) -> list[CategoryContent]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT c.twitch_category_id AS category_id, c.name, COALESCE(s.theme_key, 'stream_os_generic') AS theme_key,
                       COALESCE(s.enabled, TRUE) AS enabled
                FROM stream_categories c LEFT JOIN game_category_settings s ON s.twitch_category_id = c.twitch_category_id
                ORDER BY c.last_seen_at DESC
            """)).all()
        return [CategoryContent(**dict(row._mapping)) for row in rows]

    def save_category_setting(self, category_id: str, theme_key: str, enabled: bool) -> CategoryContent:
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO game_category_settings (twitch_category_id, theme_key, enabled)
                VALUES (:id, :theme, :enabled)
                ON DUPLICATE KEY UPDATE theme_key = VALUES(theme_key), enabled = VALUES(enabled)
            """), {"id": category_id, "theme": theme_key, "enabled": enabled})
            row = connection.execute(text("""
                SELECT c.twitch_category_id AS category_id, c.name, s.theme_key, s.enabled
                FROM stream_categories c JOIN game_category_settings s ON s.twitch_category_id = c.twitch_category_id
                WHERE c.twitch_category_id = :id
            """), {"id": category_id}).one()
        return CategoryContent(**dict(row._mapping))

    def items(self) -> list[ItemDefinition]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, twitch_category_id AS category_id, name, rarity, slot, effect_type, effect_value, weight, enabled
                FROM game_item_definitions ORDER BY created_at DESC
            """)).all()
        return [ItemDefinition(**dict(row._mapping)) for row in rows]

    def create_item(self, item: ItemDefinitionInput) -> ItemDefinition:
        with self.engine.begin() as connection:
            result = connection.execute(text("""
                INSERT INTO game_item_definitions (twitch_category_id, name, rarity, slot, effect_type, effect_value, weight)
                VALUES (NULLIF(:category_id, ''), :name, :rarity, :slot, :effect_type, :effect_value, :weight)
            """), item.model_dump())
            row = connection.execute(text("""
                SELECT id, twitch_category_id AS category_id, name, rarity, slot, effect_type, effect_value, weight, enabled
                FROM game_item_definitions WHERE id=:id
            """), {"id": result.lastrowid}).one()
        return ItemDefinition(**dict(row._mapping))

    def _upsert_actor(self, connection: Any, actor: ChatActor, now: datetime) -> None:
        connection.execute(text("""
            INSERT INTO twitch_users (twitch_user_id, login, display_name, first_seen_at, last_seen_at)
            VALUES (:id, :login, :name, :now, :now)
            ON DUPLICATE KEY UPDATE login = VALUES(login), display_name = VALUES(display_name), last_seen_at = VALUES(last_seen_at)
        """), {"id": actor.user_id, "login": actor.login, "name": actor.display_name, "now": now})

    def register_player(self, actor: ChatActor) -> tuple[PlayerProfile, bool]:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            self._upsert_actor(connection, actor, now)
            inserted = connection.execute(text("""
                INSERT IGNORE INTO game_players (twitch_user_id, last_active_at) VALUES (:id, :now)
            """), {"id": actor.user_id, "now": now}).rowcount == 1
            row = connection.execute(text("""
                SELECT p.twitch_user_id AS user_id, u.display_name, p.level, p.xp, p.credits
                FROM game_players p JOIN twitch_users u ON u.twitch_user_id = p.twitch_user_id WHERE p.twitch_user_id = :id
            """), {"id": actor.user_id}).one()
        return PlayerProfile(**dict(row._mapping)), inserted

    def player(self, user_id: str) -> PlayerProfile | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT p.twitch_user_id AS user_id, u.display_name, p.level, p.xp, p.credits
                FROM game_players p JOIN twitch_users u ON u.twitch_user_id = p.twitch_user_id WHERE p.twitch_user_id = :id
            """), {"id": user_id}).first()
        return PlayerProfile(**dict(row._mapping)) if row else None

    def active_encounter(self) -> EncounterState | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT id, COALESCE(twitch_category_id, '') AS category_id, boss_name, max_hp, current_hp,
                       max_party_integrity, party_integrity, round_number, round_seconds, boss_damage, round_ends_at, status
                FROM game_encounters WHERE status = 'active' ORDER BY created_at DESC LIMIT 1
            """)).first()
        return self._encounter(row) if row else None

    def start_encounter(self, category_id: str, boss_name: str, max_hp: int, boss_damage: int, round_seconds: int) -> EncounterState:
        if self.active_encounter():
            raise GameError("Ya hay un boss activo. Finalízalo o cancélalo antes de iniciar otro.")
        now = datetime.now(timezone.utc)
        state = new_encounter(category_id, boss_name, max_hp, boss_damage, round_seconds, now)
        with self.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO game_encounters (id, twitch_category_id, boss_name, max_hp, current_hp, max_party_integrity,
                    party_integrity, round_number, round_seconds, boss_damage, round_ends_at, status)
                VALUES (:id, NULLIF(:category_id, ''), :boss_name, :max_hp, :current_hp, :max_party_integrity,
                    :party_integrity, :round_number, :round_seconds, :boss_damage, :round_ends_at, :status)
            """), state.model_dump())
            connection.execute(text("""
                INSERT INTO game_boss_definitions (twitch_category_id, name, max_hp, base_party_damage, round_seconds)
                VALUES (NULLIF(:category_id, ''), :boss_name, :max_hp, :boss_damage, :round_seconds)
            """), {"category_id": category_id, "boss_name": boss_name, "max_hp": max_hp, "boss_damage": boss_damage, "round_seconds": round_seconds})
        return state

    def add_action(self, encounter_id: str, actor: ChatActor, action: str, message_id: str) -> str:
        now = datetime.now(timezone.utc)
        try:
            with self.engine.begin() as connection:
                self._upsert_actor(connection, actor, now)
                player = connection.execute(text("SELECT 1 FROM game_players WHERE twitch_user_id = :id"), {"id": actor.user_id}).first()
                if not player:
                    return "Regístrate primero con !join."
                encounter = connection.execute(text("SELECT status, round_number, round_ends_at FROM game_encounters WHERE id = :id FOR UPDATE"), {"id": encounter_id}).one_or_none()
                if not encounter or encounter.status != "active":
                    return "No hay un boss activo."
                if encounter.round_ends_at <= now:
                    return "La ronda acaba de cerrar; espera la siguiente."
                connection.execute(text("""
                    INSERT INTO game_encounter_actions (encounter_id, round_number, twitch_user_id, action_type, source_message_id)
                    VALUES (:encounter_id, :round, :player_id, :action, :message_id)
                """), {"encounter_id": encounter_id, "round": encounter.round_number, "player_id": actor.user_id, "action": action, "message_id": message_id})
                connection.execute(text("UPDATE game_players SET last_active_at = :now WHERE twitch_user_id = :id"), {"now": now, "id": actor.user_id})
            return f"{action.upper()} registrado para la ronda actual."
        except IntegrityError:
            return "Ya registraste una acción en esta ronda."

    def resolve_due_encounter(self) -> tuple[EncounterState, dict[str, int | str]] | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            row = connection.execute(text("""
                SELECT id, COALESCE(twitch_category_id, '') AS category_id, boss_name, max_hp, current_hp,
                       max_party_integrity, party_integrity, round_number, round_seconds, boss_damage, round_ends_at, status
                FROM game_encounters WHERE status = 'active' AND round_ends_at <= :now ORDER BY created_at DESC LIMIT 1 FOR UPDATE
            """), {"now": now}).first()
            if not row:
                return None
            state = self._encounter(row)
            actions = connection.execute(text("SELECT twitch_user_id, action_type FROM game_encounter_actions WHERE encounter_id = :id AND round_number = :round"), {"id": state.id, "round": state.round_number}).all()
            result, updated = resolve_round(state, [item.action_type for item in actions], state.boss_damage, now)
            connection.execute(text("""
                INSERT INTO game_round_results (encounter_id, round_number, attack_damage, defend_value, heal_value, boss_damage, resolved_at)
                VALUES (:id, :round, :attack_damage, :defend_value, :heal_value, :boss_damage, :now)
            """), {"id": state.id, "round": state.round_number, **result, "now": now})
            connection.execute(text("""
                UPDATE game_encounters SET current_hp=:current_hp, party_integrity=:party_integrity, round_number=:round_number,
                    round_ends_at=:round_ends_at, status=:status, version=version+1, ended_at=CASE WHEN :status='active' THEN NULL ELSE :now END
                WHERE id=:id
            """), {**updated.model_dump(), "now": now})
            for action in actions:
                source_id = f"{state.id}:{state.round_number}"
                reward = connection.execute(text("""
                    INSERT IGNORE INTO game_rewards (twitch_user_id, source_type, source_id, xp, credits)
                    VALUES (:user_id, 'round', :source_id, :xp, :credits)
                """), {"user_id": action.twitch_user_id, "source_id": source_id, "xp": XP_PER_ACTION, "credits": CREDITS_PER_ACTION})
                if reward.rowcount:
                    connection.execute(text("UPDATE game_players SET xp=xp+:xp, credits=credits+:credits WHERE twitch_user_id=:id"), {"xp": XP_PER_ACTION, "credits": CREDITS_PER_ACTION, "id": action.twitch_user_id})
        return updated, result

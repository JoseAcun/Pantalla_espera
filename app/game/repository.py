"""MariaDB adapter for the first STREAM_OS RPG slice."""

from datetime import datetime, timezone
import random
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.game.models import (
    CategoryContent,
    ChatActor,
    EncounterState,
    ItemDefinition,
    ItemDefinitionInput,
    PlayerProfile,
    PlayerQuest,
    QuestCompletion,
    QuestDefinition,
    QuestDefinitionInput,
)
from app.game.service import CREDITS_PER_ACTION, XP_PER_ACTION, GAME_TIMEZONE, GameError, boss_intent, new_encounter, quest_period_key, resolve_round


class GameRepository:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(database_url, pool_pre_ping=True)

    @staticmethod
    def _encounter(row: Any) -> EncounterState:
        state = EncounterState(**dict(row._mapping))
        return state.model_copy(update={"boss_intent": boss_intent(state.id, state.round_number)})

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

    def quests(self) -> list[QuestDefinition]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, twitch_category_id AS category_id, cadence, name, description,
                       objective_type, objective_target, reward_xp, reward_credits,
                       reward_random_item, enabled
                FROM game_quest_definitions
                ORDER BY cadence, created_at DESC
            """)).all()
        return [QuestDefinition(**dict(row._mapping)) for row in rows]

    def create_quest(self, quest: QuestDefinitionInput) -> QuestDefinition:
        with self.engine.begin() as connection:
            result = connection.execute(text("""
                INSERT INTO game_quest_definitions (
                    twitch_category_id, cadence, name, description, objective_type,
                    objective_target, reward_xp, reward_credits, reward_random_item
                ) VALUES (
                    NULLIF(:category_id, ''), :cadence, :name, :description, :objective_type,
                    :objective_target, :reward_xp, :reward_credits, :reward_random_item
                )
            """), quest.model_dump())
            row = connection.execute(text("""
                SELECT id, twitch_category_id AS category_id, cadence, name, description,
                       objective_type, objective_target, reward_xp, reward_credits,
                       reward_random_item, enabled
                FROM game_quest_definitions WHERE id = :id
            """), {"id": result.lastrowid}).one()
        return QuestDefinition(**dict(row._mapping))

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

    def player_quests(self, user_id: str, category_id: str = "") -> list[PlayerQuest]:
        now = datetime.now(timezone.utc)
        daily_key = quest_period_key("daily", now)
        weekly_key = quest_period_key("weekly", now)
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT q.id, q.cadence, q.name, q.description, q.objective_type, q.objective_target,
                       q.reward_xp, q.reward_credits, q.reward_random_item,
                       COALESCE(p.progress, 0) AS progress, p.completed_at IS NOT NULL AS completed
                FROM game_quest_definitions q
                LEFT JOIN game_player_quest_progress p ON p.twitch_user_id = :user_id
                  AND p.quest_definition_id = q.id
                  AND p.period_key = CASE WHEN q.cadence = 'weekly' THEN :weekly_key ELSE :daily_key END
                WHERE q.enabled = TRUE
                  AND (q.twitch_category_id IS NULL OR q.twitch_category_id = NULLIF(:category_id, ''))
                ORDER BY FIELD(q.cadence, 'daily', 'weekly'), q.id
            """), {"user_id": user_id, "category_id": category_id, "daily_key": daily_key, "weekly_key": weekly_key}).all()
        return [PlayerQuest(**dict(row._mapping)) for row in rows]

    def record_chat_activity(self, actor: ChatActor, message_id: str, category_id: str = "") -> list[QuestCompletion]:
        """Credit one non-command chat message per minute, 20-minute window and stream day."""
        now = datetime.now(timezone.utc)
        local = now.astimezone(GAME_TIMEZONE)
        window_minute = local.minute - local.minute % 20
        activity_keys = {
            "chat_messages": f"chat:{local:%Y%m%d%H%M}",
            "activity_windows": f"window:{local:%Y%m%d%H}{window_minute:02d}",
            "stream_days": f"stream-day:{local.date().isoformat()}",
        }
        with self.engine.begin() as connection:
            self._upsert_actor(connection, actor, now)
            if not connection.execute(text("SELECT 1 FROM game_players WHERE twitch_user_id = :id"), {"id": actor.user_id}).first():
                return []
            completions: list[QuestCompletion] = []
            for objective_type, activity_key in activity_keys.items():
                inserted = connection.execute(text("""
                    INSERT IGNORE INTO game_player_activity
                      (twitch_user_id, activity_type, activity_key, source_message_id, occurred_at)
                    VALUES (:user_id, :activity_type, :activity_key, :message_id, :now)
                """), {"user_id": actor.user_id, "activity_type": objective_type, "activity_key": activity_key, "message_id": message_id, "now": now})
                if inserted.rowcount:
                    completions.extend(self._advance_quests(connection, actor.user_id, category_id, objective_type, now))
            connection.execute(text("UPDATE game_players SET last_active_at = :now WHERE twitch_user_id = :id"), {"now": now, "id": actor.user_id})
        return completions

    def record_raid_action(self, actor: ChatActor, message_id: str, category_id: str = "") -> list[QuestCompletion]:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            inserted = connection.execute(text("""
                INSERT IGNORE INTO game_player_activity
                  (twitch_user_id, activity_type, activity_key, source_message_id, occurred_at)
                VALUES (:user_id, 'raid_actions', :message_id, :message_id, :now)
            """), {"user_id": actor.user_id, "message_id": message_id, "now": now})
            if not inserted.rowcount:
                return []
            return self._advance_quests(connection, actor.user_id, category_id, "raid_actions", now)

    def _advance_quests(self, connection: Any, user_id: str, category_id: str, objective_type: str, now: datetime) -> list[QuestCompletion]:
        quests = connection.execute(text("""
            SELECT id, cadence, name, objective_target, reward_xp, reward_credits, reward_random_item
            FROM game_quest_definitions
            WHERE enabled = TRUE AND objective_type = :objective_type
              AND (twitch_category_id IS NULL OR twitch_category_id = NULLIF(:category_id, ''))
        """), {"objective_type": objective_type, "category_id": category_id}).all()
        completions: list[QuestCompletion] = []
        for row in quests:
            quest = dict(row._mapping)
            period_key = quest_period_key(quest["cadence"], now)
            progress_row = connection.execute(text("""
                SELECT progress, completed_at FROM game_player_quest_progress
                WHERE twitch_user_id = :user_id AND quest_definition_id = :quest_id AND period_key = :period_key
                FOR UPDATE
            """), {"user_id": user_id, "quest_id": quest["id"], "period_key": period_key}).first()
            current = int(progress_row.progress) if progress_row else 0
            if progress_row and progress_row.completed_at is not None:
                continue
            progress = min(int(quest["objective_target"]), current + 1)
            completed = progress >= int(quest["objective_target"])
            if progress_row:
                connection.execute(text("""
                    UPDATE game_player_quest_progress
                    SET progress = :progress, completed_at = CASE WHEN :completed THEN :now ELSE NULL END
                    WHERE twitch_user_id = :user_id AND quest_definition_id = :quest_id AND period_key = :period_key
                """), {"progress": progress, "completed": completed, "now": now, "user_id": user_id, "quest_id": quest["id"], "period_key": period_key})
            else:
                connection.execute(text("""
                    INSERT INTO game_player_quest_progress
                      (twitch_user_id, quest_definition_id, period_key, progress, completed_at)
                    VALUES (:user_id, :quest_id, :period_key, :progress, CASE WHEN :completed THEN :now ELSE NULL END)
                """), {"user_id": user_id, "quest_id": quest["id"], "period_key": period_key, "progress": progress, "completed": completed, "now": now})
            if not completed:
                continue
            source_id = f"quest:{quest['id']}:{period_key}"
            reward = connection.execute(text("""
                INSERT IGNORE INTO game_rewards (twitch_user_id, source_type, source_id, xp, credits)
                VALUES (:user_id, 'quest', :source_id, :xp, :credits)
            """), {"user_id": user_id, "source_id": source_id, "xp": quest["reward_xp"], "credits": quest["reward_credits"]})
            if not reward.rowcount:
                continue
            connection.execute(text("""
                UPDATE game_players
                SET xp = xp + :xp, credits = credits + :credits,
                    level = 1 + FLOOR((xp + :xp) / 100)
                WHERE twitch_user_id = :user_id
            """), {"xp": quest["reward_xp"], "credits": quest["reward_credits"], "user_id": user_id})
            item_name = ""
            if quest["reward_random_item"]:
                item = self._random_item(connection, category_id)
                if item:
                    connection.execute(text("""
                        INSERT IGNORE INTO game_player_items (twitch_user_id, item_definition_id, source_type, source_id)
                        VALUES (:user_id, :item_id, 'quest', :source_id)
                    """), {"user_id": user_id, "item_id": item["id"], "source_id": source_id})
                    connection.execute(text("""
                        UPDATE game_player_quest_progress SET reward_item_definition_id = :item_id
                        WHERE twitch_user_id = :user_id AND quest_definition_id = :quest_id AND period_key = :period_key
                    """), {"item_id": item["id"], "user_id": user_id, "quest_id": quest["id"], "period_key": period_key})
                    item_name = item["name"]
            completions.append(QuestCompletion(name=quest["name"], xp=quest["reward_xp"], credits=quest["reward_credits"], item_name=item_name))
        return completions

    @staticmethod
    def _random_item(connection: Any, category_id: str) -> dict[str, Any] | None:
        rows = connection.execute(text("""
            SELECT id, name, weight FROM game_item_definitions
            WHERE enabled = TRUE AND (twitch_category_id IS NULL OR twitch_category_id = NULLIF(:category_id, ''))
        """), {"category_id": category_id}).all()
        if not rows:
            return None
        values = [dict(row._mapping) for row in rows]
        return random.choices(values, weights=[item["weight"] for item in values], k=1)[0]

    def active_encounter(self) -> EncounterState | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                SELECT id, COALESCE(twitch_category_id, '') AS category_id, boss_name, max_hp, current_hp,
                       max_party_integrity, party_integrity, round_number, round_seconds, boss_damage, round_ends_at, status
                FROM game_encounters WHERE status = 'active' ORDER BY created_at DESC LIMIT 1
            """)).first()
        return self._encounter(row) if row else None

    def start_encounter(self, category_id: str, boss_name: str, max_hp: int, boss_damage: int, round_seconds: int, party_integrity: int) -> EncounterState:
        if self.active_encounter():
            raise GameError("Ya hay un boss activo. Finalízalo o cancélalo antes de iniciar otro.")
        now = datetime.now(timezone.utc)
        state = new_encounter(category_id, boss_name, max_hp, boss_damage, round_seconds, party_integrity, now)
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

    def resolve_due_encounter(self, force: bool = False) -> tuple[EncounterState, dict[str, int | str]] | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            condition = "" if force else "AND round_ends_at <= :now"
            row = connection.execute(text(f"""
                SELECT id, COALESCE(twitch_category_id, '') AS category_id, boss_name, max_hp, current_hp,
                       max_party_integrity, party_integrity, round_number, round_seconds, boss_damage, round_ends_at, status
                FROM game_encounters WHERE status = 'active' {condition} ORDER BY created_at DESC LIMIT 1 FOR UPDATE
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

    def cancel_active_encounter(self) -> EncounterState | None:
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            row = connection.execute(text("""
                SELECT id, COALESCE(twitch_category_id, '') AS category_id, boss_name, max_hp, current_hp,
                       max_party_integrity, party_integrity, round_number, round_seconds, boss_damage, round_ends_at, status
                FROM game_encounters WHERE status = 'active' ORDER BY created_at DESC LIMIT 1 FOR UPDATE
            """)).first()
            if not row:
                return None
            state = self._encounter(row).model_copy(update={"status": "cancelled"})
            connection.execute(text("UPDATE game_encounters SET status='cancelled', ended_at=:now, version=version+1 WHERE id=:id"), {"now": now, "id": state.id})
        return state

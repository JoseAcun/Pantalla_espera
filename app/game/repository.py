"""MariaDB adapter for the first STREAM_OS RPG slice."""

from datetime import datetime, timezone
import random
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.game.models import (
    CategoryContent,
    ChatActor,
    CommunityCompleter,
    CommunityDashboard,
    CommunityQuest,
    CommunitySeason,
    EncounterState,
    ItemDefinition,
    ItemDefinitionInput,
    PlayerProfile,
    PlayerQuest,
    PublicGameEvent,
    QuestCompletion,
    QuestDefinition,
    QuestDefinitionInput,
    QuestDefinitionUpdate,
    Season,
    SeasonInput,
    SeasonLeader,
)
from app.game.service import CREDITS_PER_ACTION, XP_PER_ACTION, GAME_TIMEZONE, GameError, boss_intent, new_encounter, quest_period_key, resolve_round


def _utc(value: datetime) -> datetime:
    """MariaDB DATETIME is timezone-less; this project stores it as UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


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

    def update_quest(self, quest_id: int, quest: QuestDefinitionUpdate) -> QuestDefinition:
        with self.engine.begin() as connection:
            result = connection.execute(text("""
                UPDATE game_quest_definitions
                SET twitch_category_id = NULLIF(:category_id, ''), cadence = :cadence,
                    name = :name, description = :description, objective_type = :objective_type,
                    objective_target = :objective_target, reward_xp = :reward_xp,
                    reward_credits = :reward_credits, reward_random_item = :reward_random_item,
                    enabled = :enabled
                WHERE id = :id
            """), {**quest.model_dump(), "id": quest_id})
            if not result.rowcount:
                raise GameError("La misión ya no existe.")
            row = connection.execute(text("""
                SELECT id, twitch_category_id AS category_id, cadence, name, description,
                       objective_type, objective_target, reward_xp, reward_credits,
                       reward_random_item, enabled
                FROM game_quest_definitions WHERE id = :id
            """), {"id": quest_id}).one()
        return QuestDefinition(**dict(row._mapping))

    def seasons(self) -> list[Season]:
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, name, slug, starts_at, ends_at, active
                FROM game_seasons ORDER BY starts_at DESC, id DESC
            """)).all()
        return [Season(**{**dict(row._mapping), "starts_at": _utc(row.starts_at), "ends_at": _utc(row.ends_at)}) for row in rows]

    def create_season(self, season: SeasonInput) -> Season:
        self._validate_season_dates(season)
        with self.engine.begin() as connection:
            self._assert_no_active_season_overlap(connection, season)
            result = connection.execute(text("""
                INSERT INTO game_seasons (name, slug, starts_at, ends_at, active)
                VALUES (:name, :slug, :starts_at, :ends_at, :active)
            """), season.model_dump())
            row = connection.execute(text("""
                SELECT id, name, slug, starts_at, ends_at, active
                FROM game_seasons WHERE id = :id
            """), {"id": result.lastrowid}).one()
        return Season(**{**dict(row._mapping), "starts_at": _utc(row.starts_at), "ends_at": _utc(row.ends_at)})

    def update_season(self, season_id: int, season: SeasonInput) -> Season:
        self._validate_season_dates(season)
        with self.engine.begin() as connection:
            self._assert_no_active_season_overlap(connection, season, season_id)
            result = connection.execute(text("""
                UPDATE game_seasons
                SET name=:name, slug=:slug, starts_at=:starts_at, ends_at=:ends_at, active=:active
                WHERE id=:id
            """), {**season.model_dump(), "id": season_id})
            if not result.rowcount:
                raise GameError("La temporada ya no existe.")
            row = connection.execute(text("""
                SELECT id, name, slug, starts_at, ends_at, active
                FROM game_seasons WHERE id = :id
            """), {"id": season_id}).one()
        return Season(**{**dict(row._mapping), "starts_at": _utc(row.starts_at), "ends_at": _utc(row.ends_at)})

    @staticmethod
    def _validate_season_dates(season: SeasonInput) -> None:
        if season.ends_at <= season.starts_at:
            raise GameError("El cierre de la temporada debe ser posterior a su inicio.")

    @staticmethod
    def _assert_no_active_season_overlap(connection: Any, season: SeasonInput, excluded_id: int | None = None) -> None:
        if not season.active:
            return
        row = connection.execute(text("""
            SELECT id FROM game_seasons
            WHERE active = TRUE AND starts_at <= :ends_at AND ends_at >= :starts_at
              AND (:excluded_id IS NULL OR id <> :excluded_id)
            LIMIT 1 FOR UPDATE
        """), {"starts_at": season.starts_at, "ends_at": season.ends_at, "excluded_id": excluded_id}).first()
        if row:
            raise GameError("Ya existe otra temporada activa en ese rango de fechas.")

    def recent_public_events(self, limit: int = 20) -> list[PublicGameEvent]:
        safe_limit = max(1, min(int(limit), 20))
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT e.id, e.event_type, COALESCE(u.display_name, 'SYSTEM') AS display_name,
                       e.title, e.detail, e.occurred_at
                FROM game_public_events e
                LEFT JOIN twitch_users u ON u.twitch_user_id = e.twitch_user_id
                ORDER BY e.occurred_at DESC, e.id DESC
                LIMIT :limit
            """), {"limit": safe_limit}).all()
        return [PublicGameEvent(**{**dict(row._mapping), "occurred_at": _utc(row.occurred_at)}) for row in rows]

    def active_public_quests(self, category_id: str = "", now: datetime | None = None) -> list[CommunityQuest]:
        now = now or datetime.now(timezone.utc)
        daily_key = quest_period_key("daily", now)
        weekly_key = quest_period_key("weekly", now)
        with self.engine.connect() as connection:
            rows = connection.execute(text("""
                SELECT id, cadence, name, description, objective_type, objective_target,
                       reward_xp, reward_credits
                FROM game_quest_definitions
                WHERE enabled = TRUE
                  AND (twitch_category_id IS NULL OR twitch_category_id = NULLIF(:category_id, ''))
                  AND cadence IN ('daily', 'weekly')
                ORDER BY FIELD(cadence, 'daily', 'weekly'), id ASC
            """), {"category_id": category_id}).all()
            selected: dict[str, dict[str, Any]] = {}
            for row in rows:
                quest = dict(row._mapping)
                selected.setdefault(quest["cadence"], quest)
            quests: list[CommunityQuest] = []
            for cadence in ("daily", "weekly"):
                quest = selected.get(cadence)
                if not quest:
                    continue
                period_key = daily_key if cadence == "daily" else weekly_key
                totals = connection.execute(text("""
                    SELECT COUNT(*) AS participants,
                           COALESCE(SUM(completed_at IS NOT NULL), 0) AS completions
                    FROM game_player_quest_progress
                    WHERE quest_definition_id = :quest_id AND period_key = :period_key
                """), {"quest_id": quest["id"], "period_key": period_key}).one()
                completers = connection.execute(text("""
                    SELECT u.display_name, p.completed_at
                    FROM game_player_quest_progress p
                    JOIN twitch_users u ON u.twitch_user_id = p.twitch_user_id
                    WHERE p.quest_definition_id = :quest_id AND p.period_key = :period_key
                      AND p.completed_at IS NOT NULL
                    ORDER BY p.completed_at DESC, u.display_name ASC
                    LIMIT 5
                """), {"quest_id": quest["id"], "period_key": period_key}).all()
                quests.append(CommunityQuest(
                    **quest,
                    period_key=period_key,
                    participants=int(totals.participants),
                    completions=int(totals.completions),
                    recent_completers=[CommunityCompleter(**{**dict(item._mapping), "completed_at": _utc(item.completed_at)}) for item in completers],
                ))
        return quests

    def active_season_leaders(self, limit: int = 5, now: datetime | None = None) -> CommunitySeason | None:
        safe_limit = max(1, min(int(limit), 5))
        now = now or datetime.now(timezone.utc)
        with self.engine.connect() as connection:
            season_row = connection.execute(text("""
                SELECT id, name, starts_at, ends_at
                FROM game_seasons
                WHERE active = TRUE AND starts_at <= :now AND ends_at >= :now
                ORDER BY starts_at DESC, id DESC LIMIT 1
            """), {"now": now}).first()
            if not season_row:
                return None
            season = dict(season_row._mapping)
            rows = connection.execute(text("""
                SELECT u.display_name,
                       (SELECT COUNT(*) FROM game_player_quest_progress p
                        WHERE p.twitch_user_id = gp.twitch_user_id
                          AND p.completed_at >= :starts_at AND p.completed_at <= :ends_at) AS missions_completed,
                       (SELECT COALESCE(SUM(r.xp), 0) FROM game_rewards r
                        WHERE r.twitch_user_id = gp.twitch_user_id
                          AND r.created_at >= :starts_at AND r.created_at <= :ends_at) AS season_xp,
                       (SELECT MAX(p.completed_at) FROM game_player_quest_progress p
                        WHERE p.twitch_user_id = gp.twitch_user_id
                          AND p.completed_at >= :starts_at AND p.completed_at <= :ends_at) AS last_completed_at
                FROM game_players gp
                JOIN twitch_users u ON u.twitch_user_id = gp.twitch_user_id
                HAVING missions_completed > 0 OR season_xp > 0
                ORDER BY missions_completed DESC, season_xp DESC, last_completed_at DESC, u.display_name ASC
                LIMIT :limit
            """), {"starts_at": season["starts_at"], "ends_at": season["ends_at"], "limit": safe_limit}).all()
        leaders = [SeasonLeader(rank=index, display_name=row.display_name, missions_completed=int(row.missions_completed), season_xp=int(row.season_xp)) for index, row in enumerate(rows, start=1)]
        starts_at, ends_at = _utc(season["starts_at"]), _utc(season["ends_at"])
        days_remaining = max(0, (ends_at.date() - now.astimezone(timezone.utc).date()).days)
        return CommunitySeason(name=season["name"], starts_at=starts_at, ends_at=ends_at, days_remaining=days_remaining, leaders=leaders)

    def community_dashboard(self, category_id: str = "", now: datetime | None = None) -> CommunityDashboard:
        now = now or datetime.now(timezone.utc)
        return CommunityDashboard(
            generated_at=now,
            quests=self.active_public_quests(category_id, now),
            user_log=self.recent_public_events(20),
            season=self.active_season_leaders(5, now),
        )

    def _record_public_event(self, connection: Any, user_id: str | None, event_type: str, title: str, detail: str, source_key: str, now: datetime) -> PublicGameEvent | None:
        result = connection.execute(text("""
            INSERT IGNORE INTO game_public_events
              (twitch_user_id, event_type, title, detail, source_key, occurred_at)
            VALUES (:user_id, :event_type, :title, :detail, :source_key, :now)
        """), {
            "user_id": user_id, "event_type": event_type[:40], "title": title[:120],
            "detail": detail[:255], "source_key": source_key[:128], "now": now,
        })
        if not result.rowcount:
            return None
        row = connection.execute(text("""
            SELECT e.id, e.event_type, COALESCE(u.display_name, 'SYSTEM') AS display_name,
                   e.title, e.detail, e.occurred_at
            FROM game_public_events e
            LEFT JOIN twitch_users u ON u.twitch_user_id = e.twitch_user_id
            WHERE e.id = :id
        """), {"id": result.lastrowid}).one()
        return PublicGameEvent(**{**dict(row._mapping), "occurred_at": _utc(row.occurred_at)})

    def _upsert_actor(self, connection: Any, actor: ChatActor, now: datetime) -> None:
        connection.execute(text("""
            INSERT INTO twitch_users (twitch_user_id, login, display_name, first_seen_at, last_seen_at)
            VALUES (:id, :login, :name, :now, :now)
            ON DUPLICATE KEY UPDATE login = VALUES(login), display_name = VALUES(display_name), last_seen_at = VALUES(last_seen_at)
        """), {"id": actor.user_id, "login": actor.login, "name": actor.display_name, "now": now})

    def register_player(self, actor: ChatActor) -> tuple[PlayerProfile, bool, PublicGameEvent | None]:
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
            public_event = self._record_public_event(
                connection, actor.user_id, "player_joined", "NEW PLAYER INITIALIZED", "",
                f"player-joined:{actor.user_id}", now,
            ) if inserted else None
        return PlayerProfile(**dict(row._mapping)), inserted, public_event

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
        player = connection.execute(text("""
            SELECT xp, level FROM game_players WHERE twitch_user_id = :user_id FOR UPDATE
        """), {"user_id": user_id}).one()
        current_xp = int(player.xp)
        current_level = int(player.level)
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
            level_before = current_level
            current_xp += int(quest["reward_xp"])
            current_level = 1 + current_xp // 100
            connection.execute(text("""
                UPDATE game_players
                SET xp = :xp, credits = credits + :credits, level = :level
                WHERE twitch_user_id = :user_id
            """), {"xp": current_xp, "credits": quest["reward_credits"], "level": current_level, "user_id": user_id})
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
            detail = f"{quest['name']} // +{quest['reward_xp']} XP +{quest['reward_credits']} C"
            if item_name:
                detail += f" // {item_name}"
            public_events = []
            completion_event = self._record_public_event(
                connection, user_id, "quest_completed", "MISSION COMPLETE", detail,
                f"quest-completed:{user_id}:{quest['id']}:{period_key}", now,
            )
            if completion_event:
                public_events.append(completion_event)
            if current_level > level_before:
                level_event = self._record_public_event(
                    connection, user_id, "level_up", "LEVEL INCREASED", f"LV {current_level:02d}",
                    f"level-up:{user_id}:{quest['id']}:{period_key}", now,
                )
                if level_event:
                    public_events.append(level_event)
            completions.append(QuestCompletion(
                quest_id=int(quest["id"]), period_key=period_key, name=quest["name"],
                xp=int(quest["reward_xp"]), credits=int(quest["reward_credits"]), item_name=item_name,
                level_before=level_before, level_after=current_level, public_events=public_events,
            ))
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

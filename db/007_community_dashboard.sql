-- STREAM_OS: BRB Community Dashboard persistence.
-- Run once after 006_stream_analytics_session_fk.sql. This migration preserves
-- all existing RPG and stream analytics records.

USE twitch_overlay;

CREATE TABLE IF NOT EXISTS game_seasons (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(100) NOT NULL,
  slug VARCHAR(64) NOT NULL,
  starts_at DATETIME(6) NOT NULL,
  ends_at DATETIME(6) NOT NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  UNIQUE KEY uq_game_season_slug (slug),
  KEY idx_game_season_active_dates (active, starts_at, ends_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_public_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_user_id VARCHAR(32) NULL,
  event_type VARCHAR(40) NOT NULL,
  title VARCHAR(120) NOT NULL,
  detail VARCHAR(255) NOT NULL DEFAULT '',
  metadata_json JSON NULL,
  source_key VARCHAR(128) NULL,
  occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_game_public_event_source (source_key),
  KEY idx_game_public_events_time (occurred_at DESC),
  KEY idx_game_public_events_user_time (twitch_user_id, occurred_at DESC),
  CONSTRAINT fk_public_event_player
    FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX idx_quest_progress_dashboard
  ON game_player_quest_progress (quest_definition_id, period_key, completed_at DESC);

CREATE INDEX idx_game_rewards_season
  ON game_rewards (created_at DESC, twitch_user_id);

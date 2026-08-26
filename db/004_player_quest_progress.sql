-- STREAM_OS RPG: personal quest progress, anti-spam activity windows and item rewards.
-- Run once after 003_quest_catalog.sql.

USE twitch_overlay;

CREATE TABLE IF NOT EXISTS game_player_quest_progress (
  twitch_user_id VARCHAR(32) NOT NULL,
  quest_definition_id BIGINT UNSIGNED NOT NULL,
  period_key VARCHAR(32) NOT NULL,
  progress INT UNSIGNED NOT NULL DEFAULT 0,
  completed_at DATETIME(6) NULL,
  reward_item_definition_id BIGINT UNSIGNED NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (twitch_user_id, quest_definition_id, period_key),
  KEY idx_quest_progress_period (quest_definition_id, period_key),
  CONSTRAINT fk_quest_progress_player FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id),
  CONSTRAINT fk_quest_progress_definition FOREIGN KEY (quest_definition_id) REFERENCES game_quest_definitions (id),
  CONSTRAINT fk_quest_progress_reward_item FOREIGN KEY (reward_item_definition_id) REFERENCES game_item_definitions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_player_activity (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_user_id VARCHAR(32) NOT NULL,
  activity_type VARCHAR(32) NOT NULL,
  activity_key VARCHAR(80) NOT NULL,
  source_message_id VARCHAR(64) NOT NULL,
  occurred_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_player_activity_bucket (twitch_user_id, activity_type, activity_key),
  KEY idx_player_activity_time (twitch_user_id, occurred_at DESC),
  CONSTRAINT fk_player_activity_player FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_player_items (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_user_id VARCHAR(32) NOT NULL,
  item_definition_id BIGINT UNSIGNED NOT NULL,
  source_type VARCHAR(32) NOT NULL,
  source_id VARCHAR(64) NOT NULL,
  acquired_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_player_item_source (twitch_user_id, source_type, source_id),
  KEY idx_player_items (twitch_user_id, acquired_at DESC),
  CONSTRAINT fk_player_item_player FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id),
  CONSTRAINT fk_player_item_definition FOREIGN KEY (item_definition_id) REFERENCES game_item_definitions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

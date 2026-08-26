-- STREAM_OS RPG: category-aware content and the first cooperative raid slice.
-- Run once after 001_normalized_schema.sql.

USE twitch_overlay;

CREATE TABLE IF NOT EXISTS stream_categories (
  twitch_category_id VARCHAR(32) NOT NULL,
  name VARCHAR(512) NOT NULL,
  first_seen_at DATETIME(6) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  PRIMARY KEY (twitch_category_id),
  KEY idx_stream_categories_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stream_category_history (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_category_id VARCHAR(32) NOT NULL,
  observed_at DATETIME(6) NOT NULL,
  source VARCHAR(32) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_category_history_time (observed_at DESC),
  CONSTRAINT fk_category_history_category FOREIGN KEY (twitch_category_id)
    REFERENCES stream_categories (twitch_category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_category_settings (
  twitch_category_id VARCHAR(32) NOT NULL,
  theme_key VARCHAR(64) NOT NULL DEFAULT 'stream_os_generic',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (twitch_category_id),
  CONSTRAINT fk_game_category_settings_category FOREIGN KEY (twitch_category_id)
    REFERENCES stream_categories (twitch_category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_item_definitions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_category_id VARCHAR(32) NULL,
  name VARCHAR(255) NOT NULL,
  rarity ENUM('common','uncommon','rare','epic','legendary','corrupted') NOT NULL DEFAULT 'common',
  slot ENUM('weapon','armor','accessory','consumable') NOT NULL,
  effect_type VARCHAR(64) NOT NULL DEFAULT 'none',
  effect_value INT NOT NULL DEFAULT 0,
  weight INT UNSIGNED NOT NULL DEFAULT 100,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_item_category_enabled (twitch_category_id, enabled),
  CONSTRAINT fk_item_category FOREIGN KEY (twitch_category_id)
    REFERENCES stream_categories (twitch_category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_boss_definitions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_category_id VARCHAR(32) NULL,
  name VARCHAR(255) NOT NULL,
  max_hp INT UNSIGNED NOT NULL,
  base_party_damage INT UNSIGNED NOT NULL DEFAULT 12,
  round_seconds SMALLINT UNSIGNED NOT NULL DEFAULT 15,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  KEY idx_boss_category_enabled (twitch_category_id, enabled),
  CONSTRAINT fk_boss_category FOREIGN KEY (twitch_category_id)
    REFERENCES stream_categories (twitch_category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_quest_definitions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_category_id VARCHAR(32) NULL,
  cadence ENUM('daily','weekly','event') NOT NULL,
  name VARCHAR(255) NOT NULL,
  objective_type VARCHAR(64) NOT NULL,
  objective_target INT UNSIGNED NOT NULL,
  reward_xp INT UNSIGNED NOT NULL DEFAULT 0,
  reward_credits INT UNSIGNED NOT NULL DEFAULT 0,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  KEY idx_quest_category_enabled (twitch_category_id, enabled),
  CONSTRAINT fk_quest_category FOREIGN KEY (twitch_category_id)
    REFERENCES stream_categories (twitch_category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_players (
  twitch_user_id VARCHAR(32) NOT NULL,
  level INT UNSIGNED NOT NULL DEFAULT 1,
  xp INT UNSIGNED NOT NULL DEFAULT 0,
  credits INT UNSIGNED NOT NULL DEFAULT 0,
  player_class VARCHAR(64) NOT NULL DEFAULT 'unassigned',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  last_active_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (twitch_user_id),
  CONSTRAINT fk_game_player_user FOREIGN KEY (twitch_user_id)
    REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_encounters (
  id CHAR(36) NOT NULL,
  twitch_category_id VARCHAR(32) NULL,
  boss_definition_id BIGINT UNSIGNED NULL,
  boss_name VARCHAR(255) NOT NULL,
  max_hp INT UNSIGNED NOT NULL,
  current_hp INT UNSIGNED NOT NULL,
  max_party_integrity INT UNSIGNED NOT NULL,
  party_integrity INT UNSIGNED NOT NULL,
  round_number INT UNSIGNED NOT NULL DEFAULT 1,
  round_seconds SMALLINT UNSIGNED NOT NULL DEFAULT 15,
  boss_damage INT UNSIGNED NOT NULL DEFAULT 12,
  round_ends_at DATETIME(6) NOT NULL,
  status ENUM('active','victory','defeat','cancelled') NOT NULL DEFAULT 'active',
  version INT UNSIGNED NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ended_at DATETIME(6) NULL,
  PRIMARY KEY (id),
  KEY idx_encounter_status (status, created_at DESC),
  CONSTRAINT fk_encounter_category FOREIGN KEY (twitch_category_id)
    REFERENCES stream_categories (twitch_category_id),
  CONSTRAINT fk_encounter_boss FOREIGN KEY (boss_definition_id)
    REFERENCES game_boss_definitions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_encounter_actions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  encounter_id CHAR(36) NOT NULL,
  round_number INT UNSIGNED NOT NULL,
  twitch_user_id VARCHAR(32) NOT NULL,
  action_type ENUM('attack','defend','heal') NOT NULL,
  source_message_id VARCHAR(64) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_action_message (source_message_id),
  UNIQUE KEY uq_action_player_round (encounter_id, round_number, twitch_user_id),
  KEY idx_actions_encounter_round (encounter_id, round_number),
  CONSTRAINT fk_action_encounter FOREIGN KEY (encounter_id) REFERENCES game_encounters (id),
  CONSTRAINT fk_action_player FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_round_results (
  encounter_id CHAR(36) NOT NULL,
  round_number INT UNSIGNED NOT NULL,
  attack_damage INT UNSIGNED NOT NULL,
  defend_value INT UNSIGNED NOT NULL,
  heal_value INT UNSIGNED NOT NULL,
  boss_damage INT UNSIGNED NOT NULL,
  resolved_at DATETIME(6) NOT NULL,
  PRIMARY KEY (encounter_id, round_number),
  CONSTRAINT fk_round_result_encounter FOREIGN KEY (encounter_id) REFERENCES game_encounters (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS game_rewards (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_user_id VARCHAR(32) NOT NULL,
  source_type VARCHAR(64) NOT NULL,
  source_id VARCHAR(64) NOT NULL,
  xp INT UNSIGNED NOT NULL DEFAULT 0,
  credits INT UNSIGNED NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_reward_source_player (twitch_user_id, source_type, source_id),
  CONSTRAINT fk_reward_player FOREIGN KEY (twitch_user_id) REFERENCES game_players (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

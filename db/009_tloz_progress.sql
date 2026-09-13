-- TLOZ V1: Zelda game catalogue, manual playthrough state and persistent recap.
-- This is additive and idempotent. It shares the existing twitch_overlay MariaDB only.
USE twitch_overlay;

CREATE TABLE IF NOT EXISTS tloz_games (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  slug VARCHAR(64) NOT NULL,
  title VARCHAR(160) NOT NULL,
  twitch_category_id VARCHAR(32) NULL,
  chronology_order SMALLINT UNSIGNED NOT NULL DEFAULT 100,
  era VARCHAR(80) NOT NULL DEFAULT '',
  release_year SMALLINT UNSIGNED NULL,
  platform VARCHAR(80) NOT NULL DEFAULT '',
  layout_key ENUM('16_9','4_3','handheld','ds','3ds') NOT NULL DEFAULT '16_9',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_tloz_games_slug (slug),
  UNIQUE KEY uq_tloz_games_twitch_category (twitch_category_id),
  KEY idx_tloz_games_timeline (enabled, chronology_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tloz_zones (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  game_id BIGINT UNSIGNED NOT NULL,
  name VARCHAR(160) NOT NULL,
  chronology_order SMALLINT UNSIGNED NOT NULL DEFAULT 100,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tloz_zone_name (game_id, name),
  KEY idx_tloz_zone_order (game_id, chronology_order),
  CONSTRAINT fk_tloz_zone_game FOREIGN KEY (game_id) REFERENCES tloz_games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tloz_objectives (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  zone_id BIGINT UNSIGNED NOT NULL,
  title VARCHAR(255) NOT NULL,
  kind ENUM('required','optional') NOT NULL DEFAULT 'required',
  chronology_order SMALLINT UNSIGNED NOT NULL DEFAULT 100,
  description VARCHAR(500) NOT NULL DEFAULT '',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (id),
  KEY idx_tloz_objective_order (zone_id, chronology_order),
  CONSTRAINT fk_tloz_objective_zone FOREIGN KEY (zone_id) REFERENCES tloz_zones(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tloz_playthroughs (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  game_id BIGINT UNSIGNED NOT NULL,
  twitch_stream_id VARCHAR(64) NULL,
  console_name VARCHAR(80) NOT NULL DEFAULT '',
  special_state VARCHAR(80) NOT NULL DEFAULT '',
  current_zone_id BIGINT UNSIGNED NULL,
  current_objective_id BIGINT UNSIGNED NULL,
  active BOOLEAN NOT NULL DEFAULT TRUE,
  started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_tloz_playthrough_active (game_id, active, updated_at),
  CONSTRAINT fk_tloz_playthrough_game FOREIGN KEY (game_id) REFERENCES tloz_games(id),
  CONSTRAINT fk_tloz_playthrough_zone FOREIGN KEY (current_zone_id) REFERENCES tloz_zones(id),
  CONSTRAINT fk_tloz_playthrough_objective FOREIGN KEY (current_objective_id) REFERENCES tloz_objectives(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tloz_objective_progress (
  playthrough_id BIGINT UNSIGNED NOT NULL,
  objective_id BIGINT UNSIGNED NOT NULL,
  completed_at DATETIME(6) NULL,
  PRIMARY KEY (playthrough_id, objective_id),
  KEY idx_tloz_progress_completed (playthrough_id, completed_at),
  CONSTRAINT fk_tloz_objective_progress_playthrough FOREIGN KEY (playthrough_id) REFERENCES tloz_playthroughs(id),
  CONSTRAINT fk_tloz_objective_progress_objective FOREIGN KEY (objective_id) REFERENCES tloz_objectives(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS tloz_progress_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  playthrough_id BIGINT UNSIGNED NOT NULL,
  event_type ENUM('playthrough_started','zone_entered','objective_selected','objective_completed','special_state_changed') NOT NULL,
  zone_id BIGINT UNSIGNED NULL,
  objective_id BIGINT UNSIGNED NULL,
  special_state VARCHAR(80) NOT NULL DEFAULT '',
  occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_tloz_events_recap (playthrough_id, occurred_at),
  CONSTRAINT fk_tloz_event_playthrough FOREIGN KEY (playthrough_id) REFERENCES tloz_playthroughs(id),
  CONSTRAINT fk_tloz_event_zone FOREIGN KEY (zone_id) REFERENCES tloz_zones(id),
  CONSTRAINT fk_tloz_event_objective FOREIGN KEY (objective_id) REFERENCES tloz_objectives(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

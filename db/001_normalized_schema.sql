-- Twitch Stream Overlay: normalized MariaDB schema
-- Run with a privileged MariaDB user once. All timestamps are stored in UTC.

CREATE DATABASE IF NOT EXISTS twitch_overlay
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE twitch_overlay;

-- Twitch IDs are strings in API contracts. Do not model them as numeric IDs.
CREATE TABLE IF NOT EXISTS twitch_users (
  twitch_user_id VARCHAR(32) NOT NULL,
  login VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  first_seen_at DATETIME(6) NOT NULL,
  last_seen_at DATETIME(6) NOT NULL,
  PRIMARY KEY (twitch_user_id),
  KEY idx_twitch_users_login (login)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Optional audit table. Insert a row only when login or display_name changes.
CREATE TABLE IF NOT EXISTS twitch_user_name_history (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_user_id VARCHAR(32) NOT NULL,
  login VARCHAR(255) NOT NULL,
  display_name VARCHAR(255) NOT NULL,
  observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_user_name_history_user_time (twitch_user_id, observed_at DESC),
  CONSTRAINT fk_user_name_history_user
    FOREIGN KEY (twitch_user_id) REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stream_sessions (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  twitch_stream_id VARCHAR(64) NOT NULL,
  broadcaster_id VARCHAR(32) NOT NULL,
  started_at DATETIME(6) NOT NULL,
  ended_at DATETIME(6) NULL,
  game_name VARCHAR(512) NOT NULL DEFAULT '',
  title VARCHAR(1024) NOT NULL DEFAULT '',
  PRIMARY KEY (id),
  UNIQUE KEY uq_stream_sessions_twitch_stream (twitch_stream_id),
  KEY idx_stream_sessions_broadcaster_start (broadcaster_id, started_at DESC),
  CONSTRAINT fk_stream_sessions_broadcaster
    FOREIGN KEY (broadcaster_id) REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Raw EventSub deliveries: audit trail and first layer of deduplication.
-- This matches the lightweight twitch_events table already used by the app.
CREATE TABLE IF NOT EXISTS twitch_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  message_id VARCHAR(64) NOT NULL,
  event_type VARCHAR(64) NOT NULL,
  payload JSON NOT NULL,
  occurred_at DATETIME(6) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_twitch_events_message_id (message_id),
  KEY idx_twitch_events_type_time (event_type, occurred_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS follows (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_message_id VARCHAR(64) NOT NULL,
  follower_id VARCHAR(32) NOT NULL,
  broadcaster_id VARCHAR(32) NOT NULL,
  followed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_follows_event (event_message_id),
  KEY idx_follows_broadcaster_time (broadcaster_id, followed_at DESC),
  KEY idx_follows_follower_time (follower_id, followed_at DESC),
  CONSTRAINT fk_follows_event
    FOREIGN KEY (event_message_id) REFERENCES twitch_events (message_id),
  CONSTRAINT fk_follows_follower
    FOREIGN KEY (follower_id) REFERENCES twitch_users (twitch_user_id),
  CONSTRAINT fk_follows_broadcaster
    FOREIGN KEY (broadcaster_id) REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS subscription_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_message_id VARCHAR(64) NOT NULL,
  subscriber_id VARCHAR(32) NOT NULL,
  broadcaster_id VARCHAR(32) NOT NULL,
  tier CHAR(4) NOT NULL,
  is_gift BOOLEAN NOT NULL DEFAULT FALSE,
  occurred_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_subscription_events_event (event_message_id),
  KEY idx_subscription_events_broadcaster_time (broadcaster_id, occurred_at DESC),
  KEY idx_subscription_events_subscriber_time (subscriber_id, occurred_at DESC),
  CONSTRAINT fk_subscription_events_event
    FOREIGN KEY (event_message_id) REFERENCES twitch_events (message_id),
  CONSTRAINT fk_subscription_events_subscriber
    FOREIGN KEY (subscriber_id) REFERENCES twitch_users (twitch_user_id),
  CONSTRAINT fk_subscription_events_broadcaster
    FOREIGN KEY (broadcaster_id) REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS cheers (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_message_id VARCHAR(64) NOT NULL,
  cheerer_id VARCHAR(32) NULL,
  broadcaster_id VARCHAR(32) NOT NULL,
  is_anonymous BOOLEAN NOT NULL DEFAULT FALSE,
  bits INT UNSIGNED NOT NULL,
  message TEXT NOT NULL,
  occurred_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_cheers_event (event_message_id),
  KEY idx_cheers_broadcaster_time (broadcaster_id, occurred_at DESC),
  KEY idx_cheers_user_time (cheerer_id, occurred_at DESC),
  CONSTRAINT fk_cheers_event
    FOREIGN KEY (event_message_id) REFERENCES twitch_events (message_id),
  CONSTRAINT fk_cheers_user
    FOREIGN KEY (cheerer_id) REFERENCES twitch_users (twitch_user_id),
  CONSTRAINT fk_cheers_broadcaster
    FOREIGN KEY (broadcaster_id) REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS raids (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_message_id VARCHAR(64) NOT NULL,
  from_broadcaster_id VARCHAR(32) NOT NULL,
  to_broadcaster_id VARCHAR(32) NOT NULL,
  viewers INT UNSIGNED NOT NULL,
  occurred_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_raids_event (event_message_id),
  KEY idx_raids_target_time (to_broadcaster_id, occurred_at DESC),
  KEY idx_raids_source_time (from_broadcaster_id, occurred_at DESC),
  CONSTRAINT fk_raids_event
    FOREIGN KEY (event_message_id) REFERENCES twitch_events (message_id),
  CONSTRAINT fk_raids_source
    FOREIGN KEY (from_broadcaster_id) REFERENCES twitch_users (twitch_user_id),
  CONSTRAINT fk_raids_target
    FOREIGN KEY (to_broadcaster_id) REFERENCES twitch_users (twitch_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS viewer_snapshots (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  stream_session_id BIGINT UNSIGNED NOT NULL,
  viewer_count INT UNSIGNED NOT NULL,
  captured_at DATETIME(6) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_viewer_snapshots_session_time (stream_session_id, captured_at),
  CONSTRAINT fk_viewer_snapshots_session
    FOREIGN KEY (stream_session_id) REFERENCES stream_sessions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Useful metric examples:
-- SELECT DATE(followed_at) AS day, COUNT(*) AS follows FROM follows GROUP BY day ORDER BY day DESC;
-- SELECT MAX(viewer_count) AS peak_viewers, AVG(viewer_count) AS avg_viewers FROM viewer_snapshots WHERE stream_session_id = ?;
-- SELECT tier, COUNT(*) AS subscriptions FROM subscription_events GROUP BY tier;

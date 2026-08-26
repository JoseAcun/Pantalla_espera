-- STREAM_OS RPG: metadata needed by the Game Master mission catalog.
-- Run once after 002_game_schema.sql.

USE twitch_overlay;

ALTER TABLE game_quest_definitions
  ADD COLUMN IF NOT EXISTS description VARCHAR(500) NOT NULL DEFAULT '' AFTER name,
  ADD COLUMN IF NOT EXISTS reward_random_item BOOLEAN NOT NULL DEFAULT FALSE AFTER reward_credits,
  ADD COLUMN IF NOT EXISTS created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) AFTER enabled;

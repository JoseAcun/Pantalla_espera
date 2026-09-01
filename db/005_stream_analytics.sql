-- Twitch Stream Overlay: relate category observations to stream sessions.
-- Run once after 004_player_quest_progress.sql. Existing history is preserved.

USE twitch_overlay;

ALTER TABLE stream_category_history
  ADD COLUMN IF NOT EXISTS stream_session_id BIGINT UNSIGNED NULL AFTER id;

CREATE INDEX IF NOT EXISTS idx_category_history_session_time
  ON stream_category_history (stream_session_id, observed_at DESC);

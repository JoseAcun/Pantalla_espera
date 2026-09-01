-- Twitch Stream Overlay: enforce the session relationship for new category history.
-- Run once after 005_stream_analytics.sql. Old history keeps NULL and is preserved.

USE twitch_overlay;

-- The information_schema guard makes the migration safe to re-run. NULL values
-- in historical rows are valid under this foreign key.
SET @has_stream_session_fk := (
  SELECT COUNT(*)
  FROM information_schema.TABLE_CONSTRAINTS
  WHERE CONSTRAINT_SCHEMA = DATABASE()
    AND TABLE_NAME = 'stream_category_history'
    AND CONSTRAINT_NAME = 'fk_category_history_stream_session'
    AND CONSTRAINT_TYPE = 'FOREIGN KEY'
);

SET @add_stream_session_fk_sql := IF(
  @has_stream_session_fk = 0,
  'ALTER TABLE stream_category_history
     ADD CONSTRAINT fk_category_history_stream_session
     FOREIGN KEY (stream_session_id) REFERENCES stream_sessions (id)
     ON DELETE SET NULL',
  'SELECT 1'
);

PREPARE add_stream_session_fk_statement FROM @add_stream_session_fk_sql;
EXECUTE add_stream_session_fk_statement;
DEALLOCATE PREPARE add_stream_session_fk_statement;

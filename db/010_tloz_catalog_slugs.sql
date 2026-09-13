-- TLOZ catalog seed support. Additive and safe after 009_tloz_progress.sql.
-- Existing panel-created rows retain NULL slugs and all playthrough/progress stays intact.
USE twitch_overlay;

SET @has_timeline_branch := (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tloz_games' AND COLUMN_NAME='timeline_branch');
SET @timeline_branch_sql := IF(@has_timeline_branch=0,
  'ALTER TABLE tloz_games ADD COLUMN timeline_branch VARCHAR(80) NOT NULL DEFAULT '''' AFTER era', 'SELECT 1');
PREPARE timeline_branch_statement FROM @timeline_branch_sql;
EXECUTE timeline_branch_statement;
DEALLOCATE PREPARE timeline_branch_statement;

SET @has_zone_slug := (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tloz_zones' AND COLUMN_NAME='slug');
SET @zone_slug_sql := IF(@has_zone_slug=0,
  'ALTER TABLE tloz_zones ADD COLUMN slug VARCHAR(80) NULL AFTER game_id', 'SELECT 1');
PREPARE zone_slug_statement FROM @zone_slug_sql;
EXECUTE zone_slug_statement;
DEALLOCATE PREPARE zone_slug_statement;

SET @has_zone_slug_key := (SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tloz_zones' AND INDEX_NAME='uq_tloz_zone_slug');
SET @zone_slug_key_sql := IF(@has_zone_slug_key=0,
  'ALTER TABLE tloz_zones ADD UNIQUE KEY uq_tloz_zone_slug (game_id, slug)', 'SELECT 1');
PREPARE zone_slug_key_statement FROM @zone_slug_key_sql;
EXECUTE zone_slug_key_statement;
DEALLOCATE PREPARE zone_slug_key_statement;

SET @has_objective_slug := (SELECT COUNT(*) FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tloz_objectives' AND COLUMN_NAME='slug');
SET @objective_slug_sql := IF(@has_objective_slug=0,
  'ALTER TABLE tloz_objectives ADD COLUMN slug VARCHAR(80) NULL AFTER zone_id', 'SELECT 1');
PREPARE objective_slug_statement FROM @objective_slug_sql;
EXECUTE objective_slug_statement;
DEALLOCATE PREPARE objective_slug_statement;

SET @has_objective_slug_key := (SELECT COUNT(*) FROM information_schema.STATISTICS
  WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tloz_objectives' AND INDEX_NAME='uq_tloz_objective_slug');
SET @objective_slug_key_sql := IF(@has_objective_slug_key=0,
  'ALTER TABLE tloz_objectives ADD UNIQUE KEY uq_tloz_objective_slug (zone_id, slug)', 'SELECT 1');
PREPARE objective_slug_key_statement FROM @objective_slug_key_sql;
EXECUTE objective_slug_key_statement;
DEALLOCATE PREPARE objective_slug_key_statement;

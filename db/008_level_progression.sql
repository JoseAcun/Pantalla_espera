-- STREAM_OS: one-time backfill for the non-linear level cache.
-- XP, credits, quest progress and inventory are preserved. The values below
-- match the default GAME_LEVEL_* settings in .env.example.

USE twitch_overlay;

DROP PROCEDURE IF EXISTS recalculate_stream_os_levels_v1;

DELIMITER //
CREATE PROCEDURE recalculate_stream_os_levels_v1()
BEGIN
  DECLARE done BOOLEAN DEFAULT FALSE;
  DECLARE player_id VARCHAR(32);
  DECLARE total_xp BIGINT UNSIGNED;
  DECLARE remaining_xp BIGINT UNSIGNED;
  DECLARE player_level INT UNSIGNED;
  DECLARE required_xp BIGINT UNSIGNED;
  DECLARE base_xp INT UNSIGNED DEFAULT 100;
  DECLARE growth DECIMAL(8,4) DEFAULT 1.1500;
  DECLARE rounding_unit INT UNSIGNED DEFAULT 5;
  DECLARE player_cursor CURSOR FOR SELECT twitch_user_id, xp FROM game_players;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;

  OPEN player_cursor;
  player_loop: LOOP
    FETCH player_cursor INTO player_id, total_xp;
    IF done THEN
      LEAVE player_loop;
    END IF;

    SET remaining_xp = total_xp;
    SET player_level = 1;
    SET required_xp = base_xp;
    WHILE remaining_xp >= required_xp DO
      SET remaining_xp = remaining_xp - required_xp;
      SET player_level = player_level + 1;
      SET required_xp = ROUND((base_xp * POW(growth, player_level - 1)) / rounding_unit, 0) * rounding_unit;
    END WHILE;

    UPDATE game_players SET level = player_level WHERE twitch_user_id = player_id;
  END LOOP;
  CLOSE player_cursor;
END//
DELIMITER ;

CALL recalculate_stream_os_levels_v1();
DROP PROCEDURE recalculate_stream_os_levels_v1;

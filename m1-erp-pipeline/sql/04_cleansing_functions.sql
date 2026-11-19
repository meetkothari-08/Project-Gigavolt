-- =============================================================================
-- Cleansing functions used by 06_cleanse_to_silver.sql
-- -----------------------------------------------------------------------------
-- Deterministic scalar functions, kept separate from the load so they can be
-- unit-tested without data (validation/validate_cleansing_functions.sql).
--
--   clean_text(t)  strip HTML tags and carriage returns, collapse runs of
--                  spaces, trim, and map empty, 'NULL' and 'N/A' to NULL.
--                  Tags are stripped BEFORE the null-token check, so
--                  '<p>N/A</p>' is nulled too.
--   clean_date(t)  MM/DD/YYYY, MM-DD-YYYY, YYYY/MM/DD, YYYY-MM-DD and
--                  ISO-8601 timestamps -> DATE
--   clean_money(t) '$1,005.00' -> 1005.00
-- =============================================================================

USE gigavolt;
SET NAMES utf8mb4 COLLATE utf8mb4_uca1400_ai_ci;

DROP FUNCTION IF EXISTS clean_text;
DROP FUNCTION IF EXISTS clean_date;
DROP FUNCTION IF EXISTS clean_money;

DELIMITER $$

CREATE FUNCTION clean_text(t TEXT) RETURNS TEXT DETERMINISTIC
RETURN NULLIF(NULLIF(NULLIF(
    TRIM(REGEXP_REPLACE(REGEXP_REPLACE(REPLACE(t, CHAR(13), ''), '<[^>]+>', ''), ' +', ' ')),
    ''), 'NULL'), 'N/A')$$

CREATE FUNCTION clean_date(t TEXT) RETURNS DATE DETERMINISTIC
BEGIN
    DECLARE c TEXT DEFAULT REPLACE(clean_text(t), '/', '-');
    IF c IS NULL THEN
        RETURN NULL;
    END IF;
    -- MM-DD-YYYY (and MM/DD/YYYY after the replace above) -> YYYY-MM-DD
    IF c REGEXP '^[0-9]{2}-[0-9]{2}-[0-9]{4}$' THEN
        RETURN CAST(CONCAT(RIGHT(c, 4), '-', LEFT(c, 5)) AS DATE);
    END IF;
    -- YYYY-MM-DD, YYYY/MM/DD and ISO timestamps: the first 10 characters
    RETURN CAST(LEFT(c, 10) AS DATE);
END$$

CREATE FUNCTION clean_money(t TEXT) RETURNS DECIMAL(10,2) DETERMINISTIC
RETURN CAST(NULLIF(REGEXP_REPLACE(clean_text(t), '[^0-9.]', ''), '') AS DECIMAL(10,2))$$

DELIMITER ;


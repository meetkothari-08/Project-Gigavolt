-- =============================================================================
-- Unit tests for the cleansing functions in sql/04_cleansing_functions.sql
-- -----------------------------------------------------------------------------
-- Needs no data: every case is a literal taken from a real defect in the raw
-- extracts. Runs in CI after the schema deploy.
--
--   mariadb gigavolt < m1-erp-pipeline/validation/validate_cleansing_functions.sql
-- =============================================================================

USE gigavolt;
SET NAMES utf8mb4 COLLATE utf8mb4_uca1400_ai_ci;

SELECT check_name, IF(actual <=> expected, 'PASS', 'FAIL') AS result
FROM (
    -- clean_text --------------------------------------------------------------
    SELECT 'clean_text: strips HTML tags' AS check_name,
           clean_text('<html><body>Replaced burnt fuse block.</body></html>') AS actual,
           'Replaced burnt fuse block.' AS expected
    UNION ALL SELECT 'clean_text: collapses and trims spaces',
           clean_text('   Backup   unit   near   loading   dock  '), 'Backup unit near loading dock'
    UNION ALL SELECT 'clean_text: removes stray carriage return',
           clean_text(CONCAT('INACTIVE', CHAR(13))), 'INACTIVE'
    UNION ALL SELECT 'clean_text: empty string -> NULL',   clean_text('   '), NULL
    UNION ALL SELECT 'clean_text: NULL token -> NULL',     clean_text('NULL'), NULL
    UNION ALL SELECT 'clean_text: tag-wrapped N/A -> NULL', clean_text('<p>N/A</p>'), NULL

    -- clean_date (five source formats) ----------------------------------------
    UNION ALL SELECT 'clean_date: MM/DD/YYYY',  CAST(clean_date('03/21/2024') AS CHAR), '2024-03-21'
    UNION ALL SELECT 'clean_date: MM-DD-YYYY',  CAST(clean_date('03-21-2024') AS CHAR), '2024-03-21'
    UNION ALL SELECT 'clean_date: YYYY/MM/DD',  CAST(clean_date('2024/03/21') AS CHAR), '2024-03-21'
    UNION ALL SELECT 'clean_date: YYYY-MM-DD',  CAST(clean_date('2024-03-21') AS CHAR), '2024-03-21'
    UNION ALL SELECT 'clean_date: ISO-8601 timestamp',
           CAST(clean_date('2022-02-06T00:00:00Z') AS CHAR), '2022-02-06'
    UNION ALL SELECT 'clean_date: blank -> NULL', CAST(clean_date('') AS CHAR), NULL

    -- clean_money ---------------------------------------------------------------
    UNION ALL SELECT 'clean_money: currency string',
           CAST(clean_money('$1,005.00') AS CHAR), '1005.00'
    UNION ALL SELECT 'clean_money: plain number', CAST(clean_money('384.0') AS CHAR), '384.00'
    UNION ALL SELECT 'clean_money: NULL token -> NULL', CAST(clean_money('NULL') AS CHAR), NULL
) AS cases;

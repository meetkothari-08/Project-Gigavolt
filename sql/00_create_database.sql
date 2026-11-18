-- =============================================================================
-- Gigavolt ERP lakehouse: database bootstrap
-- -----------------------------------------------------------------------------
-- Creates the `gigavolt` schema. Least-privilege application accounts are
-- shown (commented) in 14_security_views.sql.
-- Target: MariaDB 10.11+ (developed on MariaDB 12.3).
-- =============================================================================

CREATE DATABASE IF NOT EXISTS gigavolt
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_uca1400_ai_ci;

USE gigavolt;

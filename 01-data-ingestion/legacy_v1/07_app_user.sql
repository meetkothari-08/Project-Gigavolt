-- Application login (replace the placeholder password before running)
CREATE USER IF NOT EXISTS 'gigavolt_app'@'localhost'IDENTIFIED BY '<change-me>';
GRANT SELECT,INSERT,UPDATE,DELETE ON gigavolt_erp.* TO 'gigavolt_app'@'localhost';
FLUSH PRIVILEGES;
SELECT user, host FROM mysql.user WHERE user='gigavolt_app';

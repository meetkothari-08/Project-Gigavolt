"""Relational retrieval: equipment, service history, warranty and parts."""

from __future__ import annotations

import logging

import pymysql
import pymysql.cursors

from gigavolt.config import MariaDBSettings, get_settings
from gigavolt.retry import retry_with_reconnect

logger = logging.getLogger(__name__)

# MySQL client errors that indicate a dropped connection rather than a bad query:
# 2006 server has gone away, 2013 lost connection, 2055 lost connection (SSL).
TRANSIENT_ERROR_CODES = {2006, 2013, 2055}


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, pymysql.InterfaceError):
        return True
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    return code in TRANSIENT_ERROR_CODES


retry_database_operation = retry_with_reconnect(
    (pymysql.OperationalError, pymysql.InterfaceError),
    should_retry=_is_transient,
    label="MariaDB",
)


class MariaDBRetriever:
    """Read-only access to the six cleaned Gigavolt Silver tables."""

    ALLOWED_TABLES = {
        "customers",
        "equipment",
        "equipment_models",
        "dispatches",
        "parts",
        "warranty_claims",
    }

    TEXT_TYPES = {"varchar", "char", "text", "mediumtext", "longtext"}

    def __init__(self, settings: MariaDBSettings | None = None):
        self.settings = settings or get_settings().mariadb
        self.connection = None
        self.reconnect()

    def reconnect(self) -> None:
        """Open a fresh connection, closing the previous one if present."""
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:  # noqa: BLE001 - best effort close
                pass

        self.connection = pymysql.connect(
            host=self.settings.host,
            port=self.settings.port,
            user=self.settings.user,
            password=self.settings.password,
            database=self.settings.database,
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=30,
            write_timeout=30,
        )
        logger.info("MariaDB connection established.")

    @retry_database_operation
    def test_connection(self) -> dict:
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS database_name")
            return cursor.fetchone()

    @retry_database_operation
    def get_customer(self, customer_id: str) -> dict | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM customers WHERE customer_id = %s",
                (customer_id,),
            )
            return cursor.fetchone()

    @retry_database_operation
    def get_equipment(self, equipment_id: str) -> dict | None:
        """Equipment row joined with its customer and model attributes."""
        query = """
            SELECT
                e.*,
                c.company_name,
                c.contact_name,
                c.city,
                c.state,
                em.capacity_kw,
                em.voltage
            FROM equipment e
            LEFT JOIN customers c
                ON e.customer_id = c.customer_id
            LEFT JOIN equipment_models em
                ON e.model = em.model
            WHERE e.equipment_id = %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query, (equipment_id,))
            return cursor.fetchone()

    @retry_database_operation
    def get_equipment_history(self, equipment_id: str, limit: int = 20) -> list[dict]:
        query = """
            SELECT *
            FROM dispatches
            WHERE equipment_id = %s
            ORDER BY dispatch_date DESC
            LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query, (equipment_id, limit))
            return list(cursor.fetchall())

    @retry_database_operation
    def get_warranty_claims(self, equipment_id: str, limit: int = 20) -> list[dict]:
        query = """
            SELECT *
            FROM warranty_claims
            WHERE equipment_id = %s
            ORDER BY claim_date DESC
            LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query, (equipment_id, limit))
            return list(cursor.fetchall())

    @retry_database_operation
    def get_parts(
        self,
        search_term: str | None = None,
        low_stock_only: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        query = "SELECT * FROM parts WHERE 1=1"
        params: list = []

        if search_term:
            query += """
                AND (
                    part_name LIKE %s
                    OR category LIKE %s
                    OR manufacturer LIKE %s
                    OR supplier LIKE %s
                )
            """
            term = f"%{search_term}%"
            params.extend([term, term, term, term])

        if low_stock_only:
            query += " AND stock_quantity <= reorder_level"

        query += " ORDER BY part_name LIMIT %s"
        params.append(limit)

        with self.connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchall())

    @retry_database_operation
    def get_cell_components(self, limit: int = 5) -> list[dict]:
        """Lithium-cell parts and their suppliers (supply-chain questions)."""
        query = """
            SELECT
                part_id,
                part_name,
                category,
                manufacturer,
                supplier,
                stock_quantity,
                reorder_level
            FROM parts
            WHERE LOWER(part_name) LIKE '%%lithium%%'
               OR LOWER(category) LIKE '%%lithium%%'
               OR LOWER(part_name) LIKE '%%cell%%'
               OR LOWER(category) LIKE '%%cell%%'
            LIMIT %s
        """
        with self.connection.cursor() as cursor:
            cursor.execute(query, (limit,))
            return list(cursor.fetchall())

    @retry_database_operation
    def search_table(self, table_name: str, search_term: str, limit: int = 20) -> list[dict]:
        """Case-insensitive LIKE search across every text column of an allow-listed table.

        Table and column names come from the allow-list and INFORMATION_SCHEMA,
        never from user input, so they are safe to interpolate.
        """
        if table_name not in self.ALLOWED_TABLES:
            raise ValueError("Table is not approved for retrieval")

        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = %s
                  AND TABLE_NAME = %s
                """,
                (self.settings.database, table_name),
            )
            text_columns = [
                row["COLUMN_NAME"]
                for row in cursor.fetchall()
                if row["DATA_TYPE"].lower() in self.TEXT_TYPES
            ]

            if not text_columns:
                return []

            conditions = " OR ".join(f"`{column}` LIKE %s" for column in text_columns)
            query = f"SELECT * FROM `{table_name}` WHERE ({conditions}) LIMIT %s"
            params = [f"%{search_term}%"] * len(text_columns) + [limit]

            cursor.execute(query, params)
            return list(cursor.fetchall())

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

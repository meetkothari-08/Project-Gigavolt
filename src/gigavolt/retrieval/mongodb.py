"""Telemetry retrieval: BMS readings and fault events stored in MongoDB."""

from __future__ import annotations

import logging
from datetime import datetime

from bson import ObjectId
from pymongo import DESCENDING, MongoClient
from pymongo.errors import (
    AutoReconnect,
    ConnectionFailure,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

from gigavolt.config import MongoDBSettings, get_settings
from gigavolt.retry import retry_with_reconnect

logger = logging.getLogger(__name__)

retry_mongodb_operation = retry_with_reconnect(
    (AutoReconnect, ConnectionFailure, NetworkTimeout, ServerSelectionTimeoutError),
    label="MongoDB",
)


class MongoDBRetriever:
    """Retrieves IoT telemetry and diagnostic records from MongoDB.

    Expected indexes (see docs/hybrid-rag.md):
    ``{equipment_id: 1, timestamp: -1}``, ``{fault_code: 1}``, ``{model: 1}``.
    """

    def __init__(self, settings: MongoDBSettings | None = None):
        self.settings = settings or get_settings().mongodb

        if not self.settings.username or not self.settings.password:
            raise ValueError("MONGODB_USERNAME and MONGODB_PASSWORD must be set")

        self.client = None
        self.reconnect()

    def reconnect(self) -> None:
        """Close the old client and establish a new connection."""
        if self.client is not None:
            self.client.close()

        self.client = MongoClient(
            host=self.settings.host,
            port=self.settings.port,
            username=self.settings.username,
            password=self.settings.password,
            authSource=self.settings.database,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=30000,
            retryReads=True,
        )
        self.db = self.client[self.settings.database]
        self.collection = self.db[self.settings.collection]
        logger.info("MongoDB client initialized.")

    @staticmethod
    def _serialize(document: dict | None) -> dict | None:
        """Make ObjectId and datetime values JSON-serializable."""
        if document is None:
            return document
        for key, value in document.items():
            if isinstance(value, ObjectId):
                document[key] = str(value)
            elif isinstance(value, datetime):
                document[key] = value.isoformat()
        return document

    def _find(self, query: dict, limit: int) -> list[dict]:
        cursor = self.collection.find(query).sort("timestamp", DESCENDING).limit(limit)
        return [self._serialize(doc) for doc in cursor]

    @retry_mongodb_operation
    def test_connection(self) -> bool:
        self.client.admin.command("ping")
        return True

    @retry_mongodb_operation
    def get_by_equipment(self, equipment_id: str, limit: int = 20) -> list[dict]:
        return self._find({"equipment_id": equipment_id}, limit)

    @retry_mongodb_operation
    def get_fault_records(
        self,
        equipment_id: str | None = None,
        severity: str | None = None,
        fault_code: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query: dict = {"fault_code": {"$ne": None}}
        if equipment_id:
            query["equipment_id"] = equipment_id
        if severity:
            query["severity"] = severity
        if fault_code:
            query["fault_code"] = fault_code
        return self._find(query, limit)

    @retry_mongodb_operation
    def get_by_time_range(
        self,
        equipment_id: str,
        start_time: str,
        end_time: str,
        limit: int = 100,
    ) -> list[dict]:
        query = {
            "equipment_id": equipment_id,
            "timestamp": {"$gte": start_time, "$lte": end_time},
        }
        return self._find(query, limit)

    @retry_mongodb_operation
    def get_by_model(self, model_keyword: str, limit: int = 50) -> list[dict]:
        return self._find({"model": {"$regex": model_keyword, "$options": "i"}}, limit)

    @retry_mongodb_operation
    def get_high_temperature_records(
        self,
        model_keyword: str,
        min_temperature: float = 40.0,
        limit: int = 50,
    ) -> list[dict]:
        query = {
            "model": {"$regex": model_keyword, "$options": "i"},
            "telemetry.temperature_c": {"$gte": min_temperature},
        }
        return self._find(query, limit)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

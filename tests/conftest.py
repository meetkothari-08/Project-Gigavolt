"""Shared fixtures and fakes. No database, model server or network is required."""

from __future__ import annotations

import re

import pytest


class FakeFastTokenizer:
    """Whitespace tokenizer exposing the subset of the HF fast-tokenizer API we use."""

    is_fast = True
    TOKEN = re.compile(r"\S+")

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False,
                 truncation=False):
        offsets = [(m.start(), m.end()) for m in self.TOKEN.finditer(text)]
        return {"input_ids": list(range(len(offsets))), "offset_mapping": offsets}

    def encode(self, text, add_special_tokens=False, truncation=False):
        return [0] * len(self.TOKEN.findall(text))


@pytest.fixture
def fake_tokenizer():
    return FakeFastTokenizer()


class FakeCursor:
    """Minimal DB-API cursor over in-memory tables, routed by SQL substring."""

    def __init__(self, tables: dict[str, list[dict]], audit: list[dict]):
        self.tables = tables
        self.audit = audit
        self._rows: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if "FROM Audit_Logs" in sql:
            last_id = params[0]
            self._rows = [row for row in self.audit if row["audit_id"] > last_id]
            return
        match = re.search(r"FROM `(\w+)`", sql)
        self._rows = [dict(row) for row in self.tables[match.group(1)]]

    def fetchmany(self, size):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


class FakeConnection:
    def __init__(self, tables, audit=None):
        self.tables = tables
        self.audit = audit or []
        self.closed = False

    def cursor(self):
        return FakeCursor(self.tables, self.audit)

    def close(self):
        self.closed = True


@pytest.fixture
def silver_tables():
    """A tiny but referentially valid Silver dataset."""
    return {
        "customers": [{"customer_id": "C-1", "company_name": "Volt Co",
                       "created_date": "2023-01-01"}],
        "equipment": [{"equipment_id": "EQ-1", "customer_id": "C-1", "model": "X-7000",
                       "install_date": "2023-02-01", "warranty_expiration": "2025-02-01"}],
        "equipment_models": [{"model": "X-7000", "capacity_kw": "500.00"}],
        "dispatches": [{"dispatch_id": "D-1", "equipment_id": "EQ-1",
                        "dispatch_date": "2024-01-05", "hours_spent": "2.5",
                        "labor_cost": "300.00"}],
        "parts": [{"part_id": "P-1", "part_name": "Lithium Cell", "unit_cost": "10",
                   "unit_price": "15", "stock_quantity": 4, "reorder_level": 10}],
        "warranty_claims": [{"claim_id": "W-1", "equipment_id": "EQ-1",
                             "claim_date": "2024-02-01", "claim_amount": "500",
                             "approved_amount": "400"}],
    }


@pytest.fixture
def fake_connection_factory():
    return FakeConnection

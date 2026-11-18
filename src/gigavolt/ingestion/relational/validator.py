"""Record-level validation rules for the six Silver tables."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


class RelationalValidator:
    """Validate records from the six cleaned Gigavolt tables."""

    PRIMARY_KEYS = {
        "customers": "customer_id",
        "equipment": "equipment_id",
        "equipment_models": "model",
        "dispatches": "dispatch_id",
        "parts": "part_id",
        "warranty_claims": "claim_id",
    }

    REQUIRED_FIELDS = {
        "customers": ["customer_id", "company_name"],
        "equipment": ["equipment_id", "model"],
        "equipment_models": ["model"],
        "dispatches": ["dispatch_id", "equipment_id"],
        "parts": ["part_id", "part_name"],
        "warranty_claims": ["claim_id", "equipment_id"],
    }

    NUMERIC_FIELDS = {
        "dispatches": ["hours_spent", "labor_cost"],
        "parts": ["unit_cost", "unit_price", "stock_quantity", "reorder_level"],
        "warranty_claims": ["claim_amount", "approved_amount"],
        "equipment_models": ["capacity_kw"],
    }

    DATE_FIELDS = {
        "customers": ["created_date"],
        "equipment": ["install_date", "warranty_expiration"],
        "dispatches": ["dispatch_date"],
        "warranty_claims": ["claim_date"],
    }

    @staticmethod
    def _to_decimal(value) -> Decimal | None:
        """Parse a numeric value; return None if it is not a finite number."""
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        return number if number.is_finite() else None

    def validate(self, table_name: str, record: dict) -> dict:
        if table_name not in self.PRIMARY_KEYS:
            return {"valid": False, "errors": ["Unapproved table"]}

        errors: list[str] = []

        for field in self.REQUIRED_FIELDS[table_name]:
            value = record.get(field)
            if value is None or str(value).strip() == "":
                errors.append(f"Missing required field: {field}")

        numbers: dict[str, Decimal] = {}
        for field in self.NUMERIC_FIELDS.get(table_name, []):
            value = record.get(field)
            if value is None or value == "":
                continue
            number = self._to_decimal(value)
            if number is None:
                errors.append(f"Invalid numeric value: {field}")
            else:
                numbers[field] = number

        for field in self.DATE_FIELDS.get(table_name, []):
            value = record.get(field)
            if value is None or value == "" or isinstance(value, (date, datetime)):
                continue
            try:
                date.fromisoformat(str(value))
            except ValueError:
                errors.append(f"Invalid date value: {field}")

        # Domain rules use only values that parsed cleanly above.
        if table_name == "parts":
            if numbers.get("stock_quantity", 0) < 0:
                errors.append("Stock quantity cannot be negative")
            if numbers.get("reorder_level", 0) < 0:
                errors.append("Reorder level cannot be negative")

        if table_name == "warranty_claims":
            claim = numbers.get("claim_amount")
            approved = numbers.get("approved_amount")
            if claim is not None and approved is not None and approved > claim:
                errors.append("Approved amount exceeds claim amount")

        return {"valid": not errors, "errors": errors}

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pymongo import ASCENDING
from pymongo.collection import Collection

from app.data.measurement_seed import (
    DEFAULT_INGREDIENT_CONVERSION_PROFILE_SEEDS,
    DEFAULT_MEASUREMENT_UNIT_SEEDS,
)
from app.models.measurement import (
    IngredientConversionProfile,
    MeasurementType,
    MeasurementUnitDefinition,
    RoundingRule,
)


class MeasurementRepository:
    def __init__(
        self,
        measurement_units_collection: Collection[dict[str, Any]],
        ingredient_conversion_profiles_collection: Collection[dict[str, Any]],
    ) -> None:
        self._measurement_units = measurement_units_collection
        self._ingredient_conversion_profiles = ingredient_conversion_profiles_collection

    def ensure_seed_data(self) -> None:
        now = datetime.now(timezone.utc)

        for seed in DEFAULT_MEASUREMENT_UNIT_SEEDS:
            payload = {
                "code": seed["code"],
                "display_name": seed["display_name"],
                "measurement_type": seed["measurement_type"],
                "canonical_unit": seed["canonical_unit"],
                "multiplier_to_canonical": seed["multiplier_to_canonical"],
                "is_fractional_allowed": seed["is_fractional_allowed"],
                "default_rounding_rule": seed["default_rounding_rule"],
                "sort_order": seed["sort_order"],
                "aliases": list(seed["aliases"]),
                "is_active": seed["is_active"],
                "updated_at": now,
            }
            self._measurement_units.update_one(
                {"_id": str(seed["id"])},
                {"$setOnInsert": {**payload, "created_at": now}},
                upsert=True,
            )

        for seed in DEFAULT_INGREDIENT_CONVERSION_PROFILE_SEEDS:
            payload = {
                "name": seed["name"],
                "ingredient_name": seed["ingredient_name"],
                "linked_product_ids": list(seed["linked_product_ids"]),
                "unit_code": seed["unit_code"],
                "canonical_quantity": seed["canonical_quantity"],
                "canonical_unit": seed["canonical_unit"],
                "notes": seed["notes"],
                "is_active": seed["is_active"],
                "updated_at": now,
            }
            self._ingredient_conversion_profiles.update_one(
                {"_id": str(seed["id"])},
                {"$setOnInsert": {**payload, "created_at": now}},
                upsert=True,
            )

    def list_units(self) -> list[MeasurementUnitDefinition]:
        documents = self._measurement_units.find({"is_active": True}).sort("sort_order", ASCENDING)
        return [self._to_unit_model(document) for document in documents]

    def list_conversion_profiles(self) -> list[IngredientConversionProfile]:
        documents = self._ingredient_conversion_profiles.find({"is_active": True}).sort("name", ASCENDING)
        return [self._to_conversion_profile_model(document) for document in documents]

    def get_unit_by_code(self, unit_code: str) -> MeasurementUnitDefinition | None:
        document = self._measurement_units.find_one({"code": unit_code, "is_active": True})
        return None if document is None else self._to_unit_model(document)

    def get_conversion_profile(self, profile_id: str) -> IngredientConversionProfile | None:
        document = self._ingredient_conversion_profiles.find_one({"_id": profile_id, "is_active": True})
        return None if document is None else self._to_conversion_profile_model(document)

    @staticmethod
    def _to_unit_model(document: dict[str, Any]) -> MeasurementUnitDefinition:
        return MeasurementUnitDefinition(
            code=str(document["code"]),
            display_name=str(document["display_name"]),
            measurement_type=MeasurementType(str(document["measurement_type"])),
            canonical_unit=str(document["canonical_unit"]),
            multiplier_to_canonical=float(document["multiplier_to_canonical"]),
            is_fractional_allowed=bool(document.get("is_fractional_allowed", True)),
            default_rounding_rule=RoundingRule(str(document["default_rounding_rule"])),
            sort_order=int(document.get("sort_order", 0)),
            aliases=[str(item) for item in document.get("aliases", [])],
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _to_conversion_profile_model(document: dict[str, Any]) -> IngredientConversionProfile:
        return IngredientConversionProfile(
            id=str(document["_id"]),
            name=str(document["name"]),
            ingredient_name=str(document.get("ingredient_name", "")),
            linked_product_ids=[str(item) for item in document.get("linked_product_ids", [])],
            unit_code=str(document["unit_code"]),
            canonical_quantity=float(document["canonical_quantity"]),
            canonical_unit=str(document["canonical_unit"]),
            notes=str(document.get("notes", "")),
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

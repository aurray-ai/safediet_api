from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.models.inventory import DeliveryFeeRule, InventoryAdjustment, InventoryAdjustmentType, InventoryItem


class InventoryRepository:
    def __init__(
        self,
        inventory_collection: Collection[dict[str, Any]],
        adjustments_collection: Collection[dict[str, Any]],
        delivery_fee_rules_collection: Collection[dict[str, Any]],
    ) -> None:
        self._inventory = inventory_collection
        self._adjustments = adjustments_collection
        self._delivery_fee_rules = delivery_fee_rules_collection

    def get_by_product_id(self, *, store_id: str, product_id: str) -> InventoryItem | None:
        document = self._inventory.find_one({"store_id": store_id, "product_id": product_id})
        return None if document is None else self._to_inventory_model(document)

    def list_inventory(
        self,
        *,
        store_id: str,
        page: int,
        page_size: int,
        search: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[InventoryItem], int]:
        query: dict[str, Any] = {"store_id": store_id}
        if is_active is not None:
            query["is_active"] = is_active
        if search:
            query["$or"] = [
                {"product_id": {"$regex": search.strip(), "$options": "i"}},
                {"sku": {"$regex": search.strip(), "$options": "i"}},
            ]
        total = self._inventory.count_documents(query)
        documents = list(
            self._inventory.find(query)
            .sort([("updated_at", DESCENDING), ("product_id", ASCENDING)])
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_inventory_model(document) for document in documents], total

    def upsert_inventory_item(
        self,
        *,
        store_id: str,
        product_id: str,
        sku: str,
        is_active: bool,
        available_quantity: int,
        reserved_quantity: int,
        unit_label: str,
        unit_weight_grams: int,
        max_per_order: int,
        allow_substitutions: bool,
        substitution_group: str | None,
    ) -> InventoryItem:
        now = datetime.now(timezone.utc)
        query = {"store_id": store_id, "product_id": product_id}
        self._inventory.update_one(
            query,
            {
                "$set": {
                    "store_id": store_id,
                    "product_id": product_id,
                    "sku": sku,
                    "is_active": is_active,
                    "available_quantity": int(available_quantity),
                    "reserved_quantity": int(reserved_quantity),
                    "unit_label": unit_label,
                    "unit_weight_grams": int(unit_weight_grams),
                    "max_per_order": int(max_per_order),
                    "allow_substitutions": allow_substitutions,
                    "substitution_group": substitution_group,
                    "updated_at": now,
                },
                "$setOnInsert": {"_id": uuid4().hex, "created_at": now},
            },
            upsert=True,
        )
        document = self._inventory.find_one(query)
        if document is None:
            raise RuntimeError("Inventory upsert did not return a document.")
        return self._to_inventory_model(document)

    def apply_adjustment(
        self,
        *,
        inventory_item_id: str,
        product_id: str,
        store_id: str,
        adjustment_type: InventoryAdjustmentType,
        delta_quantity: int,
        reason: str,
        actor_user_id: str | None,
        reference_type: str | None,
        reference_id: str | None,
        metadata: dict[str, object],
    ) -> InventoryAdjustment:
        document = {
            "_id": uuid4().hex,
            "inventory_item_id": inventory_item_id,
            "product_id": product_id,
            "store_id": store_id,
            "adjustment_type": adjustment_type.value,
            "delta_quantity": int(delta_quantity),
            "reason": reason,
            "actor_user_id": actor_user_id,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "metadata": dict(metadata or {}),
            "created_at": datetime.now(timezone.utc),
        }
        self._adjustments.insert_one(document)
        return self._to_adjustment_model(document)

    def decrement_available(
        self,
        *,
        store_id: str,
        product_id: str,
        quantity: int,
    ) -> InventoryItem:
        document = self._inventory.find_one({"store_id": store_id, "product_id": product_id})
        if document is None:
            raise ValueError("Inventory item not found.")
        available_quantity = int(document.get("available_quantity") or 0)
        if available_quantity < quantity:
            raise ValueError("Insufficient stock.")
        self._inventory.update_one(
            {"_id": document["_id"]},
            {
                "$inc": {"available_quantity": -int(quantity)},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )
        updated = self._inventory.find_one({"_id": document["_id"]})
        if updated is None:
            raise RuntimeError("Inventory item not found after decrement.")
        return self._to_inventory_model(updated)

    def increment_available(
        self,
        *,
        store_id: str,
        product_id: str,
        quantity: int,
    ) -> InventoryItem:
        document = self._inventory.find_one({"store_id": store_id, "product_id": product_id})
        if document is None:
            raise ValueError("Inventory item not found.")
        self._inventory.update_one(
            {"_id": document["_id"]},
            {
                "$inc": {"available_quantity": int(quantity)},
                "$set": {"updated_at": datetime.now(timezone.utc)},
            },
        )
        updated = self._inventory.find_one({"_id": document["_id"]})
        if updated is None:
            raise RuntimeError("Inventory item not found after increment.")
        return self._to_inventory_model(updated)

    def list_adjustments(
        self,
        *,
        product_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[InventoryAdjustment], int]:
        query = {"product_id": product_id}
        total = self._adjustments.count_documents(query)
        documents = list(
            self._adjustments.find(query)
            .sort("created_at", DESCENDING)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        return [self._to_adjustment_model(document) for document in documents], total

    def list_delivery_fee_rules(self, *, store_id: str, currency: str | None = None) -> list[DeliveryFeeRule]:
        query: dict[str, Any] = {"store_id": store_id}
        if currency:
            query["currency"] = currency
        documents = list(
            self._delivery_fee_rules.find(query).sort([("currency", ASCENDING), ("min_weight_grams", ASCENDING)])
        )
        return [self._to_delivery_fee_rule_model(document) for document in documents]

    def create_delivery_fee_rule(
        self,
        *,
        store_id: str,
        currency: str,
        min_weight_grams: int,
        max_weight_grams: int,
        fee_minor: int,
        is_active: bool,
    ) -> DeliveryFeeRule:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "store_id": store_id,
            "currency": currency,
            "min_weight_grams": int(min_weight_grams),
            "max_weight_grams": int(max_weight_grams),
            "fee_minor": int(fee_minor),
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
        }
        self._delivery_fee_rules.insert_one(document)
        return self._to_delivery_fee_rule_model(document)

    def update_delivery_fee_rule(
        self,
        *,
        rule_id: str,
        payload: dict[str, Any],
    ) -> DeliveryFeeRule | None:
        existing = self._delivery_fee_rules.find_one({"_id": rule_id})
        if existing is None:
            return None
        self._delivery_fee_rules.update_one(
            {"_id": rule_id},
            {"$set": {**payload, "updated_at": datetime.now(timezone.utc)}},
        )
        updated = self._delivery_fee_rules.find_one({"_id": rule_id})
        return None if updated is None else self._to_delivery_fee_rule_model(updated)

    @staticmethod
    def _to_inventory_model(document: dict[str, Any]) -> InventoryItem:
        return InventoryItem(
            id=str(document["_id"]),
            store_id=str(document["store_id"]),
            product_id=str(document["product_id"]),
            sku=str(document.get("sku") or ""),
            is_active=bool(document.get("is_active", True)),
            available_quantity=int(document.get("available_quantity") or 0),
            reserved_quantity=int(document.get("reserved_quantity") or 0),
            unit_label=str(document.get("unit_label") or ""),
            unit_weight_grams=int(document.get("unit_weight_grams") or 0),
            max_per_order=int(document.get("max_per_order") or 25),
            allow_substitutions=bool(document.get("allow_substitutions", True)),
            substitution_group=(
                str(document["substitution_group"])
                if document.get("substitution_group")
                else None
            ),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _to_adjustment_model(document: dict[str, Any]) -> InventoryAdjustment:
        return InventoryAdjustment(
            id=str(document["_id"]),
            inventory_item_id=str(document["inventory_item_id"]),
            product_id=str(document["product_id"]),
            store_id=str(document["store_id"]),
            adjustment_type=InventoryAdjustmentType(str(document["adjustment_type"])),
            delta_quantity=int(document["delta_quantity"]),
            reason=str(document.get("reason") or ""),
            actor_user_id=str(document["actor_user_id"]) if document.get("actor_user_id") else None,
            reference_type=str(document["reference_type"]) if document.get("reference_type") else None,
            reference_id=str(document["reference_id"]) if document.get("reference_id") else None,
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
        )

    @staticmethod
    def _to_delivery_fee_rule_model(document: dict[str, Any]) -> DeliveryFeeRule:
        return DeliveryFeeRule(
            id=str(document["_id"]),
            store_id=str(document["store_id"]),
            currency=str(document.get("currency") or "GBP"),
            min_weight_grams=int(document.get("min_weight_grams") or 0),
            max_weight_grams=int(document.get("max_weight_grams") or 0),
            fee_minor=int(document.get("fee_minor") or 0),
            is_active=bool(document.get("is_active", True)),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

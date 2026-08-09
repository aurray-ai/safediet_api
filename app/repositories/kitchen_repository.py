from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.models.grocery import CountryCode
from app.models.kitchen import (
    KitchenAllocationStatus,
    KitchenMovement,
    KitchenMovementType,
    KitchenStockLot,
    KitchenStockSourceType,
    MealPlanInventoryAllocation,
)


class KitchenRepository:
    def __init__(
        self,
        stock_lots_collection: Collection[dict[str, Any]],
        movements_collection: Collection[dict[str, Any]],
        allocations_collection: Collection[dict[str, Any]],
    ) -> None:
        self._stock_lots = stock_lots_collection
        self._movements = movements_collection
        self._allocations = allocations_collection

    def list_stock_lots(
        self,
        *,
        user_id: str,
        product_id: str | None = None,
    ) -> list[KitchenStockLot]:
        query: dict[str, Any] = {"user_id": user_id}
        if product_id:
            query["product_id"] = product_id
        documents = list(
            self._stock_lots.find(query)
            .sort([("delivered_at", ASCENDING), ("created_at", ASCENDING), ("_id", ASCENDING)])
        )
        return [self._to_stock_lot_model(document) for document in documents]

    def get_manual_stock_lot(self, *, user_id: str, product_id: str) -> KitchenStockLot | None:
        document = self._stock_lots.find_one(
            {
                "user_id": user_id,
                "product_id": product_id,
                "source_type": KitchenStockSourceType.MANUAL.value,
            }
        )
        return None if document is None else self._to_stock_lot_model(document)

    def get_order_stock_lot(self, *, user_id: str, source_id: str) -> KitchenStockLot | None:
        document = self._stock_lots.find_one(
            {
                "user_id": user_id,
                "source_type": KitchenStockSourceType.ORDER.value,
                "source_id": source_id,
            }
        )
        return None if document is None else self._to_stock_lot_model(document)

    def upsert_manual_stock_lot(
        self,
        *,
        user_id: str,
        product_id: str,
        product_name: str,
        quantity_on_hand: float,
        unit: str,
        base_unit: str,
        base_quantity_on_hand: float,
        country_code: str | None,
    ) -> KitchenStockLot:
        now = datetime.now(timezone.utc)
        query = {
            "user_id": user_id,
            "product_id": product_id,
            "source_type": KitchenStockSourceType.MANUAL.value,
        }
        existing = self._stock_lots.find_one(query)
        created_at = existing.get("created_at") if existing is not None else now
        quantity_reserved = float(existing.get("quantity_reserved") or 0.0) if existing is not None else 0.0
        quantity_consumed = float(existing.get("quantity_consumed") or 0.0) if existing is not None else 0.0
        base_quantity_reserved = float(existing.get("base_quantity_reserved") or 0.0) if existing is not None else 0.0
        base_quantity_consumed = float(existing.get("base_quantity_consumed") or 0.0) if existing is not None else 0.0
        document = {
            "_id": str(existing["_id"]) if existing is not None else uuid4().hex,
            "user_id": user_id,
            "product_id": product_id,
            "product_name": product_name,
            "source_type": KitchenStockSourceType.MANUAL.value,
            "source_id": None,
            "country_code": country_code,
            "unit": unit,
            "base_unit": base_unit,
            "quantity_on_hand": max(quantity_on_hand, 0.0),
            "quantity_reserved": max(quantity_reserved, 0.0),
            "quantity_consumed": max(quantity_consumed, 0.0),
            "base_quantity_on_hand": max(base_quantity_on_hand, 0.0),
            "base_quantity_reserved": max(base_quantity_reserved, 0.0),
            "base_quantity_consumed": max(base_quantity_consumed, 0.0),
            "delivered_at": None,
            "expires_at": None,
            "metadata": dict(existing.get("metadata") or {}) if existing is not None else {},
            "created_at": created_at,
            "updated_at": now,
        }
        self._stock_lots.replace_one(query, document, upsert=True)
        return self._to_stock_lot_model(document)

    def create_order_stock_lot(
        self,
        *,
        user_id: str,
        product_id: str,
        product_name: str,
        source_id: str,
        quantity_on_hand: float,
        unit: str,
        base_unit: str,
        base_quantity_on_hand: float,
        country_code: str | None,
        delivered_at: datetime | None,
        metadata: dict[str, object],
    ) -> KitchenStockLot:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "product_id": product_id,
            "product_name": product_name,
            "source_type": KitchenStockSourceType.ORDER.value,
            "source_id": source_id,
            "country_code": country_code,
            "unit": unit,
            "base_unit": base_unit,
            "quantity_on_hand": max(quantity_on_hand, 0.0),
            "quantity_reserved": 0.0,
            "quantity_consumed": 0.0,
            "base_quantity_on_hand": max(base_quantity_on_hand, 0.0),
            "base_quantity_reserved": 0.0,
            "base_quantity_consumed": 0.0,
            "delivered_at": delivered_at or now,
            "expires_at": None,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now,
        }
        self._stock_lots.insert_one(document)
        return self._to_stock_lot_model(document)

    def update_stock_lot_quantities(
        self,
        *,
        stock_lot_id: str,
        quantity_on_hand: float | None = None,
        quantity_reserved: float | None = None,
        quantity_consumed: float | None = None,
        base_quantity_on_hand: float | None = None,
        base_quantity_reserved: float | None = None,
        base_quantity_consumed: float | None = None,
    ) -> KitchenStockLot | None:
        updates: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if quantity_on_hand is not None:
            updates["quantity_on_hand"] = max(quantity_on_hand, 0.0)
        if quantity_reserved is not None:
            updates["quantity_reserved"] = max(quantity_reserved, 0.0)
        if quantity_consumed is not None:
            updates["quantity_consumed"] = max(quantity_consumed, 0.0)
        if base_quantity_on_hand is not None:
            updates["base_quantity_on_hand"] = max(base_quantity_on_hand, 0.0)
        if base_quantity_reserved is not None:
            updates["base_quantity_reserved"] = max(base_quantity_reserved, 0.0)
        if base_quantity_consumed is not None:
            updates["base_quantity_consumed"] = max(base_quantity_consumed, 0.0)
        self._stock_lots.update_one({"_id": stock_lot_id}, {"$set": updates})
        document = self._stock_lots.find_one({"_id": stock_lot_id})
        return None if document is None else self._to_stock_lot_model(document)

    def delete_manual_stock(self, *, user_id: str, product_id: str) -> None:
        self._stock_lots.delete_many(
            {
                "user_id": user_id,
                "product_id": product_id,
                "source_type": KitchenStockSourceType.MANUAL.value,
            }
        )

    def create_movement(
        self,
        *,
        user_id: str,
        product_id: str,
        product_name: str,
        stock_lot_id: str | None,
        movement_type: KitchenMovementType,
        quantity: float,
        base_quantity: float,
        unit: str,
        base_unit: str,
        reference_type: str | None,
        reference_id: str | None,
        note: str,
        metadata: dict[str, object] | None = None,
    ) -> KitchenMovement:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "product_id": product_id,
            "product_name": product_name,
            "stock_lot_id": stock_lot_id,
            "movement_type": movement_type.value,
            "quantity": quantity,
            "base_quantity": base_quantity,
            "unit": unit,
            "base_unit": base_unit,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "note": note,
            "metadata": metadata or {},
            "created_at": now,
        }
        self._movements.insert_one(document)
        return self._to_movement_model(document)

    def list_movements(
        self,
        *,
        user_id: str,
        product_id: str | None = None,
        limit: int = 100,
    ) -> list[KitchenMovement]:
        query: dict[str, Any] = {"user_id": user_id}
        if product_id:
            query["product_id"] = product_id
        documents = list(
            self._movements.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit)
        )
        return [self._to_movement_model(document) for document in documents]

    def list_allocations_for_saved_plan(
        self,
        *,
        user_id: str,
        saved_plan_id: str,
        slot: str | None = None,
        effective_date: date | None = None,
        status: KitchenAllocationStatus | None = None,
    ) -> list[MealPlanInventoryAllocation]:
        query: dict[str, Any] = {"user_id": user_id, "saved_plan_id": saved_plan_id}
        if slot is not None:
            query["slot"] = slot
        if effective_date is not None:
            query["effective_date"] = effective_date.isoformat()
        if status is not None:
            query["status"] = status.value
        documents = list(
            self._allocations.find(query)
            .sort([("created_at", ASCENDING), ("_id", ASCENDING)])
        )
        return [self._to_allocation_model(document) for document in documents]

    def delete_allocations_for_saved_plan(
        self,
        *,
        user_id: str,
        saved_plan_id: str,
        slot: str | None = None,
        effective_date: date | None = None,
        meal_id: str | None = None,
        status: KitchenAllocationStatus | None = None,
    ) -> list[MealPlanInventoryAllocation]:
        query: dict[str, Any] = {"user_id": user_id, "saved_plan_id": saved_plan_id}
        if slot is not None:
            query["slot"] = slot
        if effective_date is not None:
            query["effective_date"] = effective_date.isoformat()
        if meal_id is not None:
            query["meal_id"] = meal_id
        if status is not None:
            query["status"] = status.value
        documents = list(self._allocations.find(query))
        if documents:
            self._allocations.delete_many({"_id": {"$in": [document["_id"] for document in documents]}})
        return [self._to_allocation_model(document) for document in documents]

    def create_allocations(
        self,
        *,
        allocations: list[dict[str, Any]],
    ) -> list[MealPlanInventoryAllocation]:
        if not allocations:
            return []
        documents: list[dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for payload in allocations:
            document = {
                "_id": uuid4().hex,
                "user_id": payload["user_id"],
                "saved_plan_id": payload["saved_plan_id"],
                "effective_date": payload.get("effective_date"),
                "slot": payload["slot"],
                "meal_id": payload["meal_id"],
                "product_id": payload["product_id"],
                "product_name": payload["product_name"],
                "stock_lot_id": payload["stock_lot_id"],
                "required_quantity": float(payload.get("required_quantity") or 0.0),
                "reserved_quantity": float(payload.get("reserved_quantity") or 0.0),
                "consumed_quantity": float(payload.get("consumed_quantity") or 0.0),
                "unit": payload["unit"],
                "base_unit": payload["base_unit"],
                "base_required_quantity": float(payload.get("base_required_quantity") or 0.0),
                "base_reserved_quantity": float(payload.get("base_reserved_quantity") or 0.0),
                "base_consumed_quantity": float(payload.get("base_consumed_quantity") or 0.0),
                "status": KitchenAllocationStatus.RESERVED.value,
                "metadata": dict(payload.get("metadata") or {}),
                "created_at": now,
                "updated_at": now,
            }
            documents.append(document)
        self._allocations.insert_many(documents)
        return [self._to_allocation_model(document) for document in documents]

    def replace_allocation_status(
        self,
        *,
        allocation_id: str,
        status: KitchenAllocationStatus,
        consumed_quantity: float | None = None,
        base_consumed_quantity: float | None = None,
    ) -> MealPlanInventoryAllocation | None:
        updates: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(timezone.utc),
        }
        if consumed_quantity is not None:
            updates["consumed_quantity"] = max(consumed_quantity, 0.0)
        if base_consumed_quantity is not None:
            updates["base_consumed_quantity"] = max(base_consumed_quantity, 0.0)
        self._allocations.update_one({"_id": allocation_id}, {"$set": updates})
        document = self._allocations.find_one({"_id": allocation_id})
        return None if document is None else self._to_allocation_model(document)

    @staticmethod
    def _to_stock_lot_model(document: dict[str, Any]) -> KitchenStockLot:
        country_code = document.get("country_code")
        return KitchenStockLot(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            product_id=str(document["product_id"]),
            product_name=str(document.get("product_name") or ""),
            source_type=KitchenStockSourceType(str(document.get("source_type") or KitchenStockSourceType.MANUAL.value)),
            source_id=str(document["source_id"]) if document.get("source_id") else None,
            country_code=CountryCode(str(country_code)) if country_code else None,
            unit=str(document.get("unit") or ""),
            base_unit=str(document.get("base_unit") or document.get("unit") or ""),
            quantity_on_hand=float(document.get("quantity_on_hand") or 0.0),
            quantity_reserved=float(document.get("quantity_reserved") or 0.0),
            quantity_consumed=float(document.get("quantity_consumed") or 0.0),
            base_quantity_on_hand=float(document.get("base_quantity_on_hand") or document.get("quantity_on_hand") or 0.0),
            base_quantity_reserved=float(document.get("base_quantity_reserved") or document.get("quantity_reserved") or 0.0),
            base_quantity_consumed=float(document.get("base_quantity_consumed") or document.get("quantity_consumed") or 0.0),
            delivered_at=document.get("delivered_at"),
            expires_at=document.get("expires_at"),
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

    @staticmethod
    def _to_movement_model(document: dict[str, Any]) -> KitchenMovement:
        return KitchenMovement(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            product_id=str(document["product_id"]),
            product_name=str(document.get("product_name") or ""),
            stock_lot_id=str(document["stock_lot_id"]) if document.get("stock_lot_id") else None,
            movement_type=KitchenMovementType(str(document.get("movement_type") or KitchenMovementType.MANUAL_ADD.value)),
            quantity=float(document.get("quantity") or 0.0),
            base_quantity=float(document.get("base_quantity") or 0.0),
            unit=str(document.get("unit") or ""),
            base_unit=str(document.get("base_unit") or document.get("unit") or ""),
            reference_type=str(document["reference_type"]) if document.get("reference_type") else None,
            reference_id=str(document["reference_id"]) if document.get("reference_id") else None,
            note=str(document.get("note") or ""),
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
        )

    @staticmethod
    def _to_allocation_model(document: dict[str, Any]) -> MealPlanInventoryAllocation:
        effective_date_raw = document.get("effective_date")
        resolved_effective_date = (
            date.fromisoformat(str(effective_date_raw))
            if effective_date_raw not in (None, "")
            else None
        )
        return MealPlanInventoryAllocation(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            saved_plan_id=str(document["saved_plan_id"]),
            effective_date=resolved_effective_date,
            slot=str(document.get("slot") or ""),
            meal_id=str(document.get("meal_id") or ""),
            product_id=str(document.get("product_id") or ""),
            product_name=str(document.get("product_name") or ""),
            stock_lot_id=str(document.get("stock_lot_id") or ""),
            required_quantity=float(document.get("required_quantity") or 0.0),
            reserved_quantity=float(document.get("reserved_quantity") or 0.0),
            consumed_quantity=float(document.get("consumed_quantity") or 0.0),
            unit=str(document.get("unit") or ""),
            base_unit=str(document.get("base_unit") or document.get("unit") or ""),
            base_required_quantity=float(document.get("base_required_quantity") or 0.0),
            base_reserved_quantity=float(document.get("base_reserved_quantity") or 0.0),
            base_consumed_quantity=float(document.get("base_consumed_quantity") or 0.0),
            status=KitchenAllocationStatus(str(document.get("status") or KitchenAllocationStatus.RESERVED.value)),
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

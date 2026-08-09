from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import DESCENDING
from pymongo.collection import Collection

from app.models.fulfillment import AssignmentHistoryEntry, ShopperFulfillmentStatus
from app.models.order import (
    Order,
    OrderItemSnapshot,
    OrderPaymentSummary,
    OrderPricingSummary,
    OrderStatus,
    OrderStatusHistoryEntry,
    SubstitutionResolution,
)


class OrderRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def create_order(
        self,
        *,
        order_number: str,
        user_id: str,
        store_id: str,
        status: OrderStatus,
        currency: str,
        items: list[dict[str, Any]],
        pricing_summary: dict[str, Any],
        address_snapshot: dict[str, Any],
        substitution_policy: dict[str, Any],
        payment_summary: dict[str, Any],
        cancellation_window_expires_at: datetime | None,
        status_history: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> Order:
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "order_number": order_number,
            "user_id": user_id,
            "store_id": store_id,
            "status": status.value,
            "currency": currency,
            "items": items,
            "pricing_summary": pricing_summary,
            "address_snapshot": address_snapshot,
            "substitution_policy": substitution_policy,
            "payment_summary": payment_summary,
            "cancellation_window_expires_at": cancellation_window_expires_at,
            "status_history": status_history,
            "metadata": metadata,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def get_order(self, *, order_id: str) -> Order | None:
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def get_order_for_user(self, *, user_id: str, order_id: str) -> Order | None:
        document = self._collection.find_one({"_id": order_id, "user_id": user_id})
        return None if document is None else self._to_model(document)

    def list_orders_for_user(
        self,
        *,
        user_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[Order], str | None]:
        query: dict[str, Any] = {"user_id": user_id}
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]
        documents = list(
            self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return [self._to_model(document) for document in page], next_cursor

    def list_orders_admin(
        self,
        *,
        status: str | None,
        before: str | None,
        limit: int,
    ) -> tuple[list[Order], str | None]:
        query: dict[str, Any] = {}
        if status:
            query["status"] = status
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]
        documents = list(
            self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return [self._to_model(document) for document in page], next_cursor

    def update_status(
        self,
        *,
        order_id: str,
        status: OrderStatus,
        note: str,
        actor_user_id: str | None,
    ) -> Order | None:
        history_entry = {
            "status": status.value,
            "note": note,
            "actor_user_id": actor_user_id,
            "created_at": datetime.now(timezone.utc),
        }
        self._collection.update_one(
            {"_id": order_id},
            {
                "$set": {"status": status.value, "updated_at": datetime.now(timezone.utc)},
                "$push": {"status_history": history_entry},
            },
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def update_payment_summary(
        self,
        *,
        order_id: str,
        payment_summary: dict[str, Any],
    ) -> Order | None:
        self._collection.update_one(
            {"_id": order_id},
            {"$set": {"payment_summary": payment_summary, "updated_at": datetime.now(timezone.utc)}},
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def apply_refund_state(
        self,
        *,
        order_id: str,
        status: OrderStatus,
        metadata: dict[str, Any],
    ) -> Order | None:
        self._collection.update_one(
            {"_id": order_id},
            {"$set": {"status": status.value, "metadata": metadata, "updated_at": datetime.now(timezone.utc)}},
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def replace_items(
        self,
        *,
        order_id: str,
        items: list[dict[str, Any]],
    ) -> Order | None:
        self._collection.update_one(
            {"_id": order_id},
            {"$set": {"items": items, "updated_at": datetime.now(timezone.utc)}},
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def list_unassigned_for_admin(
        self,
        *,
        before: str | None,
        limit: int,
    ) -> tuple[list[Order], str | None]:
        query: dict[str, Any] = {
            "status": OrderStatus.CONFIRMED.value,
            "assigned_worker_id": None,
        }
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]
        documents = list(
            self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return [self._to_model(document) for document in page], next_cursor

    def list_for_worker(
        self,
        *,
        worker_id: str,
        before: str | None,
        limit: int,
    ) -> tuple[list[Order], str | None]:
        query: dict[str, Any] = {"assigned_worker_id": worker_id}
        if before:
            before_created_at, before_id = self._decode_cursor(before)
            query["$or"] = [
                {"created_at": {"$lt": before_created_at}},
                {"created_at": before_created_at, "_id": {"$lt": before_id}},
            ]
        documents = list(
            self._collection.find(query)
            .sort([("created_at", DESCENDING), ("_id", DESCENDING)])
            .limit(limit + 1)
        )
        has_more = len(documents) > limit
        page = documents[:limit]
        next_cursor = self._encode_cursor(page[-1]) if has_more and page else None
        return [self._to_model(document) for document in page], next_cursor

    def get_for_worker(self, *, worker_id: str, order_id: str) -> Order | None:
        document = self._collection.find_one({"_id": order_id, "assigned_worker_id": worker_id})
        return None if document is None else self._to_model(document)

    def assign_worker(
        self,
        *,
        order_id: str,
        worker_id: str,
        actor_user_id: str | None,
        note: str,
    ) -> Order | None:
        now = datetime.now(timezone.utc)
        history_entry = {
            "action": "assigned",
            "worker_id": worker_id,
            "actor_user_id": actor_user_id,
            "note": note,
            "created_at": now,
        }
        self._collection.update_one(
            {"_id": order_id},
            {
                "$set": {
                    "fulfillment_status": ShopperFulfillmentStatus.ASSIGNED.value,
                    "assigned_worker_id": worker_id,
                    "assigned_by": actor_user_id,
                    "assigned_at": now,
                    "updated_at": now,
                },
                "$push": {"assignment_history": history_entry},
            },
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def advance_fulfillment_status(
        self,
        *,
        order_id: str,
        status: ShopperFulfillmentStatus,
        actor_user_id: str | None,
        note: str,
    ) -> Order | None:
        now = datetime.now(timezone.utc)
        history_entry = {
            "action": "status_changed",
            "worker_id": None,
            "actor_user_id": actor_user_id,
            "note": note,
            "created_at": now,
        }
        self._collection.update_one(
            {"_id": order_id},
            {
                "$set": {"fulfillment_status": status.value, "updated_at": now},
                "$push": {"assignment_history": history_entry},
            },
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def record_decline(
        self,
        *,
        order_id: str,
        actor_user_id: str | None,
        reason_code: str,
        note: str,
    ) -> Order | None:
        now = datetime.now(timezone.utc)
        history_entry = {
            "action": "declined",
            "worker_id": actor_user_id,
            "actor_user_id": actor_user_id,
            "note": f"{reason_code}: {note}" if note else reason_code,
            "created_at": now,
        }
        self._collection.update_one(
            {"_id": order_id},
            {
                "$set": {
                    "fulfillment_status": ShopperFulfillmentStatus.UNASSIGNED.value,
                    "assigned_worker_id": None,
                    "assigned_by": None,
                    "assigned_at": None,
                    "updated_at": now,
                },
                "$push": {"assignment_history": history_entry},
            },
        )
        document = self._collection.find_one({"_id": order_id})
        return None if document is None else self._to_model(document)

    def count_workload_by_worker(
        self, *, worker_ids: list[str], since: datetime
    ) -> dict[str, dict[str, int]]:
        if not worker_ids:
            return {}
        active_statuses = [ShopperFulfillmentStatus.ASSIGNED.value, ShopperFulfillmentStatus.SHOPPING.value]
        pipeline = [
            {"$match": {"assigned_worker_id": {"$in": worker_ids}}},
            {
                "$group": {
                    "_id": "$assigned_worker_id",
                    "active": {"$sum": {"$cond": [{"$in": ["$fulfillment_status", active_statuses]}, 1, 0]}},
                    "completed_this_week": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$eq": ["$fulfillment_status", ShopperFulfillmentStatus.PACKED.value]},
                                        {"$gte": ["$updated_at", since]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
        results = list(self._collection.aggregate(pipeline))
        return {
            str(row["_id"]): {"active": row["active"], "completed_this_week": row["completed_this_week"]}
            for row in results
        }

    def get_overview_counts(self, *, since: datetime) -> dict[str, int]:
        unassigned = self._collection.count_documents(
            {"status": OrderStatus.CONFIRMED.value, "assigned_worker_id": None}
        )
        in_progress = self._collection.count_documents(
            {
                "fulfillment_status": {
                    "$in": [ShopperFulfillmentStatus.ASSIGNED.value, ShopperFulfillmentStatus.SHOPPING.value]
                }
            }
        )
        completed_this_week = self._collection.count_documents(
            {"fulfillment_status": ShopperFulfillmentStatus.PACKED.value, "updated_at": {"$gte": since}}
        )
        return {"unassigned": unassigned, "in_progress": in_progress, "completed_this_week": completed_this_week}

    @staticmethod
    def _encode_cursor(document: dict[str, Any]) -> str:
        created_at = document["created_at"].astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return f"{created_at}|{document['_id']}"

    @staticmethod
    def _decode_cursor(cursor: str) -> tuple[datetime, str]:
        created_at_raw, document_id = cursor.split("|", 1)
        return datetime.fromisoformat(created_at_raw.replace("Z", "+00:00")), document_id

    @staticmethod
    def _to_model(document: dict[str, Any]) -> Order:
        return Order(
            id=str(document["_id"]),
            order_number=str(document.get("order_number") or ""),
            user_id=str(document["user_id"]),
            store_id=str(document.get("store_id") or "main_store"),
            status=OrderStatus(str(document.get("status") or OrderStatus.PENDING_PAYMENT.value)),
            currency=str(document.get("currency") or "GBP"),
            items=[
                OrderItemSnapshot(
                    id=str(item.get("id") or ""),
                    product_id=str(item.get("product_id") or ""),
                    category_id=str(item.get("category_id") or ""),
                    product_name=str(item.get("product_name") or ""),
                    img_url=str(item.get("img_url") or ""),
                    quantity=int(item.get("quantity") or 0),
                    unit_label=str(item.get("unit_label") or ""),
                    unit_weight_grams=int(item.get("unit_weight_grams") or 0),
                    unit_price_minor=int(item.get("unit_price_minor") or 0),
                    line_total_minor=int(item.get("line_total_minor") or 0),
                    currency=str(item.get("currency") or document.get("currency") or "GBP"),
                    allow_substitutions=bool(item.get("allow_substitutions", True)),
                    substitution_resolution=SubstitutionResolution(
                        str(item.get("substitution_resolution") or SubstitutionResolution.NONE.value)
                    ),
                    substituted_product_id=(
                        str(item["substituted_product_id"])
                        if item.get("substituted_product_id")
                        else None
                    ),
                    source_meal_id=(
                        str(item["source_meal_id"]) if item.get("source_meal_id") else None
                    ),
                    base_price_minor=int(item.get("base_price_minor") or item.get("unit_price_minor") or 0),
                    discount_percent_applied=float(item.get("discount_percent_applied") or 0.0),
                )
                for item in list(document.get("items") or [])
            ],
            pricing_summary=OrderPricingSummary(
                currency=str((document.get("pricing_summary") or {}).get("currency") or "GBP"),
                subtotal_minor=int((document.get("pricing_summary") or {}).get("subtotal_minor") or 0),
                delivery_fee_minor=int((document.get("pricing_summary") or {}).get("delivery_fee_minor") or 0),
                service_fee_minor=int((document.get("pricing_summary") or {}).get("service_fee_minor") or 0),
                total_minor=int((document.get("pricing_summary") or {}).get("total_minor") or 0),
                total_weight_grams=int((document.get("pricing_summary") or {}).get("total_weight_grams") or 0),
            ),
            address_snapshot=dict(document.get("address_snapshot") or {}),
            substitution_policy=dict(document.get("substitution_policy") or {}),
            payment_summary=OrderPaymentSummary(
                currency=str((document.get("payment_summary") or {}).get("currency") or "GBP"),
                wallet_amount_minor=int((document.get("payment_summary") or {}).get("wallet_amount_minor") or 0),
                card_amount_minor=int((document.get("payment_summary") or {}).get("card_amount_minor") or 0),
                total_paid_minor=int((document.get("payment_summary") or {}).get("total_paid_minor") or 0),
                provider=(
                    str((document.get("payment_summary") or {}).get("provider"))
                    if (document.get("payment_summary") or {}).get("provider")
                    else None
                ),
                provider_payment_intent_id=(
                    str((document.get("payment_summary") or {}).get("provider_payment_intent_id"))
                    if (document.get("payment_summary") or {}).get("provider_payment_intent_id")
                    else None
                ),
            ),
            cancellation_window_expires_at=document.get("cancellation_window_expires_at"),
            status_history=[
                OrderStatusHistoryEntry(
                    status=OrderStatus(str(entry.get("status") or OrderStatus.PENDING_PAYMENT.value)),
                    note=str(entry.get("note") or ""),
                    actor_user_id=str(entry["actor_user_id"]) if entry.get("actor_user_id") else None,
                    created_at=entry.get("created_at") or document["created_at"],
                )
                for entry in list(document.get("status_history") or [])
            ],
            metadata=dict(document.get("metadata") or {}),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            fulfillment_status=ShopperFulfillmentStatus(
                str(document.get("fulfillment_status") or ShopperFulfillmentStatus.UNASSIGNED.value)
            ),
            assigned_worker_id=(
                str(document["assigned_worker_id"]) if document.get("assigned_worker_id") else None
            ),
            assigned_by=(str(document["assigned_by"]) if document.get("assigned_by") else None),
            assigned_at=document.get("assigned_at"),
            assignment_history=[
                AssignmentHistoryEntry(
                    action=str(entry.get("action") or ""),
                    worker_id=str(entry["worker_id"]) if entry.get("worker_id") else None,
                    actor_user_id=str(entry["actor_user_id"]) if entry.get("actor_user_id") else None,
                    note=str(entry.get("note") or ""),
                    created_at=entry.get("created_at") or document["created_at"],
                )
                for entry in list(document.get("assignment_history") or [])
            ],
        )

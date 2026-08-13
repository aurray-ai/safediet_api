from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.cart import Cart, CartItem, CartItemPricingState, CartStatus


class CartRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def get_active_cart(self, *, user_id: str) -> Cart | None:
        document = self._collection.find_one({"user_id": user_id, "status": CartStatus.ACTIVE.value})
        return None if document is None else self._to_model(document)

    def ensure_active_cart(self, *, user_id: str, store_id: str, currency: str) -> Cart:
        existing = self.get_active_cart(user_id=user_id)
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
            "store_id": store_id,
            "currency": currency,
            "status": CartStatus.ACTIVE.value,
            "items": [],
            "selected_address_id": None,
            "pricing_snapshot": {},
            "last_priced_at": None,
            "expires_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self._collection.insert_one(document)
        return self._to_model(document)

    def save_cart(
        self,
        *,
        cart_id: str,
        items: list[dict[str, Any]],
        selected_address_id: str | None,
        pricing_snapshot: dict[str, Any],
        last_priced_at: datetime | None,
        expires_at: datetime | None,
        status: CartStatus,
    ) -> Cart:
        self._collection.update_one(
            {"_id": cart_id},
            {
                "$set": {
                    "items": items,
                    "selected_address_id": selected_address_id,
                    "pricing_snapshot": pricing_snapshot,
                    "last_priced_at": last_priced_at,
                    "expires_at": expires_at,
                    "status": status.value,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
        )
        document = self._collection.find_one({"_id": cart_id})
        if document is None:
            raise RuntimeError("Cart not found after save.")
        return self._to_model(document)

    def set_selected_address(self, *, cart_id: str, address_id: str | None) -> Cart:
        self._collection.update_one(
            {"_id": cart_id},
            {"$set": {"selected_address_id": address_id, "updated_at": datetime.now(timezone.utc)}},
        )
        document = self._collection.find_one({"_id": cart_id})
        if document is None:
            raise RuntimeError("Cart not found after address update.")
        return self._to_model(document)

    def mark_converted(self, *, cart_id: str) -> None:
        self._collection.update_one(
            {"_id": cart_id},
            {"$set": {"status": CartStatus.CONVERTED.value, "updated_at": datetime.now(timezone.utc)}},
        )

    @staticmethod
    def _to_model(document: dict[str, Any]) -> Cart:
        items = [
            CartItem(
                id=str(item.get("id") or ""),
                product_id=str(item.get("product_id") or ""),
                category_id=str(item.get("category_id") or ""),
                product_name=str(item.get("product_name") or ""),
                img_url=str(item.get("img_url") or ""),
                quantity=int(item.get("quantity") or 0),
                unit_label=str(item.get("unit_label") or ""),
                unit_weight_grams=int(item.get("unit_weight_grams") or 0),
                observed_unit_price_minor=int(item.get("observed_unit_price_minor") or 0),
                current_unit_price_minor=int(item.get("current_unit_price_minor") or 0),
                currency=str(item.get("currency") or document.get("currency") or "GBP"),
                allow_substitutions=bool(item.get("allow_substitutions", True)),
                substitution_note=str(item.get("substitution_note") or ""),
                pricing_state=CartItemPricingState(
                    str(item.get("pricing_state") or CartItemPricingState.CURRENT.value)
                ),
                created_at=item.get("created_at") or document["created_at"],
                updated_at=item.get("updated_at") or document["updated_at"],
                source_saved_plan_id=(
                    str(item["source_saved_plan_id"]) if item.get("source_saved_plan_id") else None
                ),
                source_meal_ids=[str(meal_id) for meal_id in list(item.get("source_meal_ids") or [])],
                base_price_minor=int(item.get("base_price_minor") or item.get("current_unit_price_minor") or 0),
                discount_percent_applied=float(item.get("discount_percent_applied") or 0.0),
                member_price_minor=int(item.get("member_price_minor") or item.get("current_unit_price_minor") or 0),
                member_discount_percent=float(item.get("member_discount_percent") or 0.0),
            )
            for item in list(document.get("items") or [])
        ]
        return Cart(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            store_id=str(document.get("store_id") or "main_store"),
            currency=str(document.get("currency") or "GBP"),
            status=CartStatus(str(document.get("status") or CartStatus.ACTIVE.value)),
            items=items,
            selected_address_id=(
                str(document["selected_address_id"])
                if document.get("selected_address_id")
                else None
            ),
            pricing_snapshot=dict(document.get("pricing_snapshot") or {}),
            last_priced_at=document.get("last_priced_at"),
            expires_at=document.get("expires_at"),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

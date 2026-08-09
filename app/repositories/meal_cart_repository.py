from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo.collection import Collection

from app.models.cart import CartItemPricingState, CartStatus
from app.models.meal_cart import MealCart, MealCartItem


class MealCartRepository:
    def __init__(self, collection: Collection[dict[str, Any]]) -> None:
        self._collection = collection

    def get_active_cart(self, *, user_id: str) -> MealCart | None:
        document = self._collection.find_one({"user_id": user_id, "status": CartStatus.ACTIVE.value})
        return None if document is None else self._to_model(document)

    def ensure_active_cart(self, *, user_id: str, currency: str) -> MealCart:
        existing = self.get_active_cart(user_id=user_id)
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc)
        document = {
            "_id": uuid4().hex,
            "user_id": user_id,
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
    ) -> MealCart:
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
            raise RuntimeError("Meal cart not found after save.")
        return self._to_model(document)

    def set_selected_address(self, *, cart_id: str, address_id: str | None) -> MealCart:
        self._collection.update_one(
            {"_id": cart_id},
            {"$set": {"selected_address_id": address_id, "updated_at": datetime.now(timezone.utc)}},
        )
        document = self._collection.find_one({"_id": cart_id})
        if document is None:
            raise RuntimeError("Meal cart not found after address update.")
        return self._to_model(document)

    def mark_converted(self, *, cart_id: str) -> None:
        self._collection.update_one(
            {"_id": cart_id},
            {"$set": {"status": CartStatus.CONVERTED.value, "updated_at": datetime.now(timezone.utc)}},
        )

    @staticmethod
    def _to_model(document: dict[str, Any]) -> MealCart:
        items = [
            MealCartItem(
                id=str(item.get("id") or ""),
                meal_id=str(item.get("meal_id") or ""),
                meal_name=str(item.get("meal_name") or ""),
                img_url=str(item.get("img_url") or ""),
                servings=int(item.get("servings") or 0),
                observed_unit_price_minor=int(item.get("observed_unit_price_minor") or 0),
                current_unit_price_minor=int(item.get("current_unit_price_minor") or 0),
                currency=str(item.get("currency") or document.get("currency") or "GBP"),
                pricing_state=CartItemPricingState(
                    str(item.get("pricing_state") or CartItemPricingState.CURRENT.value)
                ),
                created_at=item.get("created_at") or document["created_at"],
                updated_at=item.get("updated_at") or document["updated_at"],
            )
            for item in list(document.get("items") or [])
        ]
        return MealCart(
            id=str(document["_id"]),
            user_id=str(document["user_id"]),
            currency=str(document.get("currency") or "GBP"),
            status=CartStatus(str(document.get("status") or CartStatus.ACTIVE.value)),
            items=items,
            selected_address_id=(
                str(document["selected_address_id"]) if document.get("selected_address_id") else None
            ),
            pricing_snapshot=dict(document.get("pricing_snapshot") or {}),
            last_priced_at=document.get("last_priced_at"),
            expires_at=document.get("expires_at"),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        )

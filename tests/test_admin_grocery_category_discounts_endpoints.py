from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.admin_grocery_category_discounts import (
    get_category_discount_history,
    list_category_discounts,
    reset_category_discount,
    set_category_discount,
)
from app.models.grocery import GroceryCategory, GroceryCategorySlug
from app.models.user import User, UserType
from app.schemas.category_discount import SetCategoryDiscountRequest
from app.services.category_discount_service import CategoryNotFoundError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_admin() -> User:
    return User(
        id="admin-1",
        name="Admin",
        email="admin@example.com",
        password_hash="x",
        user_types=[UserType.PLATFORM_USER],
        user_configuration={},
        created_at=utc_now(),
    )


def make_category(*, category_id: str = "cat-1", discount_percent: float | None = None) -> GroceryCategory:
    now = utc_now()
    return GroceryCategory(
        id=category_id,
        slug=GroceryCategorySlug.PROTEIN,
        name="Protein",
        icon_name="protein",
        img_url="",
        description="",
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
        discount_percent=discount_percent,
    )


class StubCategoryDiscountService:
    def __init__(self, *, categories=None, error: Exception | None = None) -> None:
        self._categories = categories or []
        self._error = error
        self.set_calls: list[dict] = []
        self.reset_calls: list[dict] = []

    def list_discounts(self):
        return self._categories

    def set_discount(self, *, category_id, discount_percent, actor_user_id):
        self.set_calls.append(
            {"category_id": category_id, "discount_percent": discount_percent, "actor_user_id": actor_user_id}
        )
        if self._error is not None:
            raise self._error
        return make_category(category_id=category_id, discount_percent=discount_percent)

    def reset_discount(self, *, category_id, actor_user_id):
        self.reset_calls.append({"category_id": category_id, "actor_user_id": actor_user_id})
        if self._error is not None:
            raise self._error
        return make_category(category_id=category_id, discount_percent=None)

    def get_discount_history(self, *, category_id):
        return [
            {
                "action": "discount_set",
                "previous_percent": None,
                "new_percent": 10.0,
                "actor_user_id": "admin-1",
                "created_at": utc_now(),
            }
        ]


class AdminGroceryCategoryDiscountsEndpointTests(unittest.TestCase):
    def test_list_category_discounts_returns_items(self) -> None:
        service = StubCategoryDiscountService(categories=[make_category(discount_percent=10.0)])

        response = list_category_discounts(_=make_admin(), category_discount_service=service)

        self.assertEqual(1, len(response.items))
        self.assertEqual(10.0, response.items[0].discount_percent)

    def test_set_category_discount_passes_payload_through(self) -> None:
        service = StubCategoryDiscountService()
        payload = SetCategoryDiscountRequest(discount_percent=25.0)

        response = set_category_discount(
            category_id="cat-1", payload=payload, current_admin=make_admin(), category_discount_service=service
        )

        self.assertEqual(1, len(service.set_calls))
        self.assertEqual("admin-1", service.set_calls[0]["actor_user_id"])
        self.assertEqual(25.0, response.discount_percent)

    def test_set_category_discount_maps_not_found_to_404(self) -> None:
        service = StubCategoryDiscountService(error=CategoryNotFoundError())
        payload = SetCategoryDiscountRequest(discount_percent=25.0)

        with self.assertRaises(HTTPException) as context:
            set_category_discount(
                category_id="missing", payload=payload, current_admin=make_admin(), category_discount_service=service
            )

        self.assertEqual(404, context.exception.status_code)

    def test_reset_category_discount_clears_override(self) -> None:
        service = StubCategoryDiscountService()

        response = reset_category_discount(
            category_id="cat-1", current_admin=make_admin(), category_discount_service=service
        )

        self.assertEqual(1, len(service.reset_calls))
        self.assertIsNone(response.discount_percent)

    def test_reset_category_discount_maps_not_found_to_404(self) -> None:
        service = StubCategoryDiscountService(error=CategoryNotFoundError())

        with self.assertRaises(HTTPException) as context:
            reset_category_discount(category_id="missing", current_admin=make_admin(), category_discount_service=service)

        self.assertEqual(404, context.exception.status_code)

    def test_get_category_discount_history_returns_entries(self) -> None:
        service = StubCategoryDiscountService()

        response = get_category_discount_history(category_id="cat-1", _=make_admin(), category_discount_service=service)

        self.assertEqual(1, len(response.items))
        self.assertEqual("discount_set", response.items[0].action)
        self.assertEqual(10.0, response.items[0].new_percent)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from fastapi import HTTPException

from app.api.v1.endpoints.admin_discounts import (
    assign_products_to_discount,
    create_discount,
    delete_discount,
    get_discount,
    get_discount_audit_log,
    list_discount_products,
    list_discounts,
    unassign_products_from_discount,
    update_discount,
)
from app.models.grocery import GroceryDiscount, GroceryProduct
from app.models.user import User, UserType
from app.schemas.discount import (
    AssignProductsToDiscountRequest,
    CreateDiscountRequest,
    UnassignProductsFromDiscountRequest,
    UpdateDiscountRequest,
)
from app.services.discount_service import DiscountNotFoundError


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


def make_discount(*, discount_id: str = "disc-1", percent: float = 10.0) -> GroceryDiscount:
    now = utc_now()
    return GroceryDiscount(id=discount_id, label=f"{percent:g}% Off", percent=percent, created_at=now, updated_at=now)


def make_product(*, product_id: str = "product-1") -> GroceryProduct:
    now = utc_now()
    return GroceryProduct(
        id=product_id,
        category_id="cat-1",
        img_url="",
        product="Chicken breast",
        product_tags=[],
        culture_tags=[],
        nutritional_specs=[],
        prices=[],
        description="",
        sort_order=1,
        is_active=True,
        created_at=now,
        updated_at=now,
    )


class StubDiscountService:
    def __init__(
        self,
        *,
        discounts: list[tuple[GroceryDiscount, int]] | None = None,
        discount: GroceryDiscount | None = None,
        products: list[GroceryProduct] | None = None,
        not_found: bool = False,
    ) -> None:
        self._discounts = discounts or []
        self._discount = discount
        self._products = products or []
        self._not_found = not_found
        self.assign_calls: list[dict] = []
        self.unassign_calls: list[dict] = []

    def list_discounts(self):
        return self._discounts

    def get_discount(self, discount_id: str):
        if self._not_found or self._discount is None:
            raise DiscountNotFoundError
        return self._discount

    def create_discount(self, *, label, percent, actor_user_id):
        return make_discount(percent=percent)

    def update_discount(self, *, discount_id, label, percent, actor_user_id):
        if self._not_found:
            raise DiscountNotFoundError
        return make_discount(discount_id=discount_id, percent=percent)

    def delete_discount(self, *, discount_id, actor_user_id):
        if self._not_found:
            raise DiscountNotFoundError

    def list_discount_products(self, *, discount_id, page, page_size, search=None):
        if self._not_found:
            raise DiscountNotFoundError
        return self._products, len(self._products)

    def assign_products(self, *, discount_id, product_ids, actor_user_id):
        if self._not_found:
            raise DiscountNotFoundError
        self.assign_calls.append({"discount_id": discount_id, "product_ids": product_ids})
        return len(product_ids)

    def unassign_products(self, *, discount_id, product_ids, actor_user_id):
        if self._not_found:
            raise DiscountNotFoundError
        self.unassign_calls.append({"discount_id": discount_id, "product_ids": product_ids})
        return len(product_ids)

    def get_audit_log(self, *, discount_id):
        return [
            {
                "action": "discount_created",
                "details": {"percent": 10.0},
                "actor_user_id": "admin-1",
                "actor_name": "Favour Emmanuel",
                "created_at": utc_now(),
            }
        ]


class AdminDiscountsEndpointsTests(unittest.TestCase):
    def test_list_discounts_returns_items_with_product_count(self) -> None:
        service = StubDiscountService(discounts=[(make_discount(), 3)])

        response = list_discounts(_=make_admin(), discount_service=service)

        self.assertEqual(1, len(response.items))
        self.assertEqual(3, response.items[0].product_count)

    def test_create_discount_returns_response(self) -> None:
        service = StubDiscountService()
        payload = CreateDiscountRequest(label="10% Off", percent=10.0)

        response = create_discount(payload=payload, current_admin=make_admin(), discount_service=service)

        self.assertEqual(10.0, response.percent)
        self.assertEqual(0, response.product_count)

    def test_get_discount_maps_not_found_to_404(self) -> None:
        service = StubDiscountService(not_found=True)

        with self.assertRaises(HTTPException) as context:
            get_discount(discount_id="missing", _=make_admin(), discount_service=service)

        self.assertEqual(404, context.exception.status_code)

    def test_update_discount_maps_not_found_to_404(self) -> None:
        service = StubDiscountService(not_found=True)
        payload = UpdateDiscountRequest(label="15% Off", percent=15.0)

        with self.assertRaises(HTTPException) as context:
            update_discount(
                discount_id="missing", payload=payload, current_admin=make_admin(), discount_service=service
            )

        self.assertEqual(404, context.exception.status_code)

    def test_delete_discount_maps_not_found_to_404(self) -> None:
        service = StubDiscountService(not_found=True)

        with self.assertRaises(HTTPException) as context:
            delete_discount(discount_id="missing", current_admin=make_admin(), discount_service=service)

        self.assertEqual(404, context.exception.status_code)

    def test_list_discount_products_returns_items(self) -> None:
        service = StubDiscountService(discount=make_discount(), products=[make_product()])

        response = list_discount_products(
            discount_id="disc-1", page=1, page_size=20, search=None, _=make_admin(), discount_service=service
        )

        self.assertEqual(1, len(response.items))
        self.assertEqual("product-1", response.items[0].id)

    def test_assign_products_passes_ids_through(self) -> None:
        service = StubDiscountService(discount=make_discount(), products=[make_product()])
        payload = AssignProductsToDiscountRequest(product_ids=["product-1", "product-2"])

        assign_products_to_discount(
            discount_id="disc-1", payload=payload, current_admin=make_admin(), discount_service=service
        )

        self.assertEqual(1, len(service.assign_calls))
        self.assertEqual(["product-1", "product-2"], service.assign_calls[0]["product_ids"])

    def test_unassign_products_passes_ids_through(self) -> None:
        service = StubDiscountService(discount=make_discount(), products=[])
        payload = UnassignProductsFromDiscountRequest(product_ids=["product-1"])

        unassign_products_from_discount(
            discount_id="disc-1", payload=payload, current_admin=make_admin(), discount_service=service
        )

        self.assertEqual(1, len(service.unassign_calls))
        self.assertEqual(["product-1"], service.unassign_calls[0]["product_ids"])

    def test_get_discount_audit_log_returns_entries(self) -> None:
        service = StubDiscountService()

        response = get_discount_audit_log(discount_id="disc-1", _=make_admin(), discount_service=service)

        self.assertEqual(1, len(response.items))
        self.assertEqual("discount_created", response.items[0].action)


if __name__ == "__main__":
    unittest.main()

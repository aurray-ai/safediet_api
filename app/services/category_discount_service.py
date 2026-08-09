from __future__ import annotations

from app.models.grocery import GroceryCategory
from app.repositories.category_discount_audit_repository import CategoryDiscountAuditRepository
from app.repositories.grocery_repository import GroceryRepository


class CategoryNotFoundError(Exception):
    pass


class CategoryDiscountService:
    def __init__(
        self,
        *,
        grocery_repository: GroceryRepository,
        audit_repository: CategoryDiscountAuditRepository,
    ) -> None:
        self._grocery_repository = grocery_repository
        self._audit_repository = audit_repository

    def list_discounts(self) -> list[GroceryCategory]:
        return self._grocery_repository.list_all_categories()

    def set_discount(self, *, category_id: str, discount_percent: float, actor_user_id: str) -> GroceryCategory:
        category = self._grocery_repository.get_any_category(category_id)
        if category is None:
            raise CategoryNotFoundError

        updated = self._grocery_repository.set_category_discount(
            category_id=category_id,
            discount_percent=discount_percent,
        )
        if updated is None:
            raise CategoryNotFoundError

        self._audit_repository.append(
            category_id=category_id,
            action="discount_set",
            previous_percent=category.discount_percent,
            new_percent=discount_percent,
            actor_user_id=actor_user_id,
        )
        return updated

    def reset_discount(self, *, category_id: str, actor_user_id: str) -> GroceryCategory:
        category = self._grocery_repository.get_any_category(category_id)
        if category is None:
            raise CategoryNotFoundError

        updated = self._grocery_repository.clear_category_discount(category_id=category_id)
        if updated is None:
            raise CategoryNotFoundError

        self._audit_repository.append(
            category_id=category_id,
            action="discount_reset",
            previous_percent=category.discount_percent,
            new_percent=None,
            actor_user_id=actor_user_id,
        )
        return updated

    def get_discount_history(self, *, category_id: str) -> list[dict]:
        return self._audit_repository.list_for_category(category_id=category_id)

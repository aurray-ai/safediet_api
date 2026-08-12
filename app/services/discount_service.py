from __future__ import annotations

from uuid import uuid4

from app.models.grocery import GroceryDiscount, GroceryProduct
from app.repositories.discount_audit_repository import DiscountAuditRepository
from app.repositories.discount_repository import DiscountRepository
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.user_repository import UserRepository


class DiscountNotFoundError(Exception):
    pass


class DiscountService:
    def __init__(
        self,
        *,
        discount_repository: DiscountRepository,
        grocery_repository: GroceryRepository,
        audit_repository: DiscountAuditRepository,
        user_repository: UserRepository,
    ) -> None:
        self._discount_repository = discount_repository
        self._grocery_repository = grocery_repository
        self._audit_repository = audit_repository
        self._user_repository = user_repository

    def list_discounts(self) -> list[tuple[GroceryDiscount, int]]:
        discounts = self._discount_repository.list_discounts()
        return [
            (discount, self._grocery_repository.count_products_by_discount(discount_id=discount.id))
            for discount in discounts
        ]

    def get_discount(self, discount_id: str) -> GroceryDiscount:
        discount = self._discount_repository.get_discount(discount_id)
        if discount is None:
            raise DiscountNotFoundError
        return discount

    def create_discount(self, *, label: str, percent: float, actor_user_id: str) -> GroceryDiscount:
        discount_id = uuid4().hex
        created = self._discount_repository.create_discount(discount_id=discount_id, label=label, percent=percent)
        self._audit_repository.append(
            discount_id=created.id,
            action="discount_created",
            details={"label": label, "percent": percent},
            actor_user_id=actor_user_id,
        )
        return created

    def update_discount(
        self,
        *,
        discount_id: str,
        label: str,
        percent: float,
        actor_user_id: str,
    ) -> GroceryDiscount:
        existing = self.get_discount(discount_id)
        updated = self._discount_repository.update_discount(discount_id=discount_id, label=label, percent=percent)
        if updated is None:
            raise DiscountNotFoundError

        self._audit_repository.append(
            discount_id=discount_id,
            action="discount_updated",
            details={
                "previous_label": existing.label,
                "previous_percent": existing.percent,
                "label": label,
                "percent": percent,
            },
            actor_user_id=actor_user_id,
        )
        return updated

    def delete_discount(self, *, discount_id: str, actor_user_id: str) -> None:
        self.get_discount(discount_id)

        unassigned_product_ids = self._grocery_repository.unassign_all_products_from_discount(
            discount_id=discount_id
        )
        deleted = self._discount_repository.delete_discount(discount_id)
        if not deleted:
            raise DiscountNotFoundError

        self._audit_repository.append(
            discount_id=discount_id,
            action="discount_deleted",
            details={"unassigned_product_count": len(unassigned_product_ids)},
            actor_user_id=actor_user_id,
        )

    def list_discount_products(
        self,
        *,
        discount_id: str,
        page: int,
        page_size: int,
        search: str | None = None,
    ) -> tuple[list[GroceryProduct], int]:
        self.get_discount(discount_id)
        return self._grocery_repository.list_products_by_discount(
            discount_id=discount_id, page=page, page_size=page_size, search=search
        )

    def assign_products(self, *, discount_id: str, product_ids: list[str], actor_user_id: str) -> int:
        self.get_discount(discount_id)
        modified = self._grocery_repository.assign_products_to_discount(
            product_ids=product_ids, discount_id=discount_id
        )
        self._audit_repository.append(
            discount_id=discount_id,
            action="products_assigned",
            details={"product_ids": product_ids, "count": modified},
            actor_user_id=actor_user_id,
        )
        return modified

    def unassign_products(self, *, discount_id: str, product_ids: list[str], actor_user_id: str) -> int:
        self.get_discount(discount_id)
        modified = self._grocery_repository.unassign_products_from_discount(product_ids=product_ids)
        self._audit_repository.append(
            discount_id=discount_id,
            action="products_unassigned",
            details={"product_ids": product_ids, "count": modified},
            actor_user_id=actor_user_id,
        )
        return modified

    def get_audit_log(self, *, discount_id: str) -> list[dict]:
        entries = self._audit_repository.list_for_discount(discount_id=discount_id)
        actor_name_cache: dict[str, str] = {}
        for entry in entries:
            actor_user_id = str(entry.get("actor_user_id") or "")
            if actor_user_id not in actor_name_cache:
                actor = self._user_repository.find_by_id(actor_user_id) if actor_user_id else None
                actor_name_cache[actor_user_id] = actor.name if actor is not None else "Unknown admin"
            entry["actor_name"] = actor_name_cache[actor_user_id]
        return entries

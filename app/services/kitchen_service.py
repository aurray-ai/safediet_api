from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from app.models.kitchen import (
    KitchenAllocationStatus,
    KitchenMovementType,
    KitchenStockLot,
)
from app.models.order import Order, OrderStatus
from app.models.user import User
from app.models.user_pantry_item import UserPantryItem
from app.repositories.kitchen_repository import KitchenRepository
from app.repositories.order_repository import OrderRepository
from app.repositories.saved_meal_plan_repository import SavedMealPlanRepository
from app.repositories.user_pantry_repository import UserPantryRepository
from app.schemas.kitchen import (
    KitchenItemResponse,
    KitchenItemUpsertRequest,
    KitchenListResponse,
    KitchenMovementListResponse,
    KitchenMovementResponse,
    KitchenOrderImportPreviewItemResponse,
    KitchenOrderImportPreviewResponse,
    KitchenOrderImportResponse,
    KitchenSummaryResponse,
    SavedPlanKitchenAllocationResponse,
    SavedPlanKitchenConsumeRequest,
    SavedPlanKitchenResponse,
)


class KitchenError(Exception):
    pass


class KitchenOrderImportError(KitchenError):
    pass


@dataclass(frozen=True, slots=True)
class _ProjectedKitchenItem:
    product_id: str
    product_name: str
    unit: str
    base_unit: str
    country_code: str | None
    quantity_on_hand: float
    quantity_reserved: float
    quantity_consumed: float
    quantity_available: float
    source_types: list[str]
    updated_at: datetime


class KitchenService:
    def __init__(
        self,
        *,
        kitchen_repository: KitchenRepository,
        user_pantry_repository: UserPantryRepository,
        order_repository: OrderRepository,
        saved_meal_plan_repository: SavedMealPlanRepository,
    ) -> None:
        self._kitchen_repository = kitchen_repository
        self._user_pantry_repository = user_pantry_repository
        self._order_repository = order_repository
        self._saved_meal_plan_repository = saved_meal_plan_repository

    def list_items(self, *, current_user: User) -> KitchenListResponse:
        items = self._projected_items(user_id=current_user.id)
        return KitchenListResponse(items=[self._to_item_response(item) for item in items])

    def get_summary(self, *, current_user: User) -> KitchenSummaryResponse:
        items = self._projected_items(user_id=current_user.id)
        low_stock_items = sum(1 for item in items if 0 < item.quantity_available <= 1)
        updated_at = max((item.updated_at for item in items), default=None)
        return KitchenSummaryResponse(
            total_items=len(items),
            available_items=sum(1 for item in items if item.quantity_available > 0),
            reserved_items=sum(1 for item in items if item.quantity_reserved > 0),
            low_stock_items=low_stock_items,
            total_available_quantity=round(sum(item.quantity_available for item in items), 2),
            total_reserved_quantity=round(sum(item.quantity_reserved for item in items), 2),
            updated_at=updated_at,
        )

    def list_movements(
        self,
        *,
        current_user: User,
        product_id: str | None = None,
        limit: int = 100,
    ) -> KitchenMovementListResponse:
        items = self._kitchen_repository.list_movements(
            user_id=current_user.id,
            product_id=product_id,
            limit=limit,
        )
        return KitchenMovementListResponse(
            items=[
                KitchenMovementResponse(
                    id=item.id,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    stock_lot_id=item.stock_lot_id,
                    movement_type=item.movement_type.value,
                    quantity=item.quantity,
                    unit=item.unit,
                    reference_type=item.reference_type,
                    reference_id=item.reference_id,
                    note=item.note,
                    created_at=item.created_at,
                )
                for item in items
            ]
        )

    def upsert_manual_item(
        self,
        *,
        current_user: User,
        payload: KitchenItemUpsertRequest,
    ) -> KitchenItemResponse:
        existing = self._kitchen_repository.get_manual_stock_lot(
            user_id=current_user.id,
            product_id=payload.product_id,
        )
        previous_quantity = existing.quantity_on_hand if existing is not None else 0.0
        lot = self._kitchen_repository.upsert_manual_stock_lot(
            user_id=current_user.id,
            product_id=payload.product_id,
            product_name=payload.product_name,
            quantity_on_hand=float(payload.quantity),
            unit=payload.unit,
            base_unit=payload.unit,
            base_quantity_on_hand=float(payload.quantity),
            country_code=payload.country_code.value if payload.country_code is not None else None,
        )
        delta = float(payload.quantity) - previous_quantity
        if delta != 0:
            self._kitchen_repository.create_movement(
                user_id=current_user.id,
                product_id=payload.product_id,
                product_name=payload.product_name,
                stock_lot_id=lot.id,
                movement_type=(
                    KitchenMovementType.MANUAL_ADD
                    if delta > 0
                    else KitchenMovementType.MANUAL_SUBTRACT
                ),
                quantity=abs(delta),
                base_quantity=abs(delta),
                unit=payload.unit,
                base_unit=payload.unit,
                reference_type="manual_kitchen",
                reference_id=payload.product_id,
                note="Manual Kitchen stock updated.",
            )
        self._sync_pantry_projection(current_user.id)
        return self._response_for_product(user_id=current_user.id, product_id=payload.product_id)

    def delete_manual_item(
        self,
        *,
        current_user: User,
        product_id: str,
    ) -> bool:
        existing = self._kitchen_repository.get_manual_stock_lot(
            user_id=current_user.id,
            product_id=product_id,
        )
        if existing is None:
            return False
        self._kitchen_repository.delete_manual_stock(
            user_id=current_user.id,
            product_id=product_id,
        )
        self._kitchen_repository.create_movement(
            user_id=current_user.id,
            product_id=existing.product_id,
            product_name=existing.product_name,
            stock_lot_id=existing.id,
            movement_type=KitchenMovementType.MANUAL_SUBTRACT,
            quantity=max(existing.quantity_on_hand, 0.0),
            base_quantity=max(existing.base_quantity_on_hand, 0.0),
            unit=existing.unit,
            base_unit=existing.base_unit,
            reference_type="manual_kitchen",
            reference_id=existing.product_id,
            note="Manual Kitchen stock removed.",
        )
        self._sync_pantry_projection(current_user.id)
        return True

    def list_planning_items(
        self,
        *,
        user_id: str,
        include_saved_plan_id: str | None = None,
    ) -> list[UserPantryItem]:
        projected = self._projected_items(
            user_id=user_id,
            include_saved_plan_id=include_saved_plan_id,
        )
        return [
            UserPantryItem(
                id=f"kitchen:{item.product_id}",
                user_id=user_id,
                product_id=item.product_id,
                product_name=item.product_name,
                quantity=item.quantity_available,
                unit=item.unit,
                country_code=None,
                created_at=item.updated_at,
                updated_at=item.updated_at,
            )
            for item in projected
            if item.quantity_available > 0
        ]

    def sync_saved_plan_allocations(
        self,
        *,
        user_id: str,
        saved_plan_id: str,
        product_demands: list[dict[str, Any]],
        effective_date: date | None,
        replace_existing: bool = True,
    ) -> None:
        if replace_existing:
            self.release_saved_plan_allocations(
                user_id=user_id,
                saved_plan_id=saved_plan_id,
                effective_date=effective_date,
            )
        if not product_demands:
            self._sync_pantry_projection(user_id)
            return

        lots = self._kitchen_repository.list_stock_lots(user_id=user_id)
        lots_by_product: dict[tuple[str, str], list[KitchenStockLot]] = defaultdict(list)
        for lot in lots:
            key = (lot.product_id, lot.unit.strip().lower())
            lots_by_product[key].append(lot)

        allocations_to_create: list[dict[str, Any]] = []
        for demand in product_demands:
            product_id = str(demand.get("product_id") or "").strip()
            unit = str(demand.get("unit") or "").strip().lower()
            required_quantity = float(demand.get("required_quantity") or 0.0)
            if not product_id or required_quantity <= 0 or not unit:
                continue

            for lot in lots_by_product.get((product_id, unit), []):
                lot_free = max(
                    lot.quantity_on_hand - lot.quantity_reserved - lot.quantity_consumed,
                    0.0,
                )
                if lot_free <= 0 or required_quantity <= 0:
                    continue
                reserved_quantity = min(lot_free, required_quantity)
                self._kitchen_repository.update_stock_lot_quantities(
                    stock_lot_id=lot.id,
                    quantity_reserved=lot.quantity_reserved + reserved_quantity,
                    base_quantity_reserved=lot.base_quantity_reserved + reserved_quantity,
                )
                self._kitchen_repository.create_movement(
                    user_id=user_id,
                    product_id=product_id,
                    product_name=str(demand.get("product_name") or lot.product_name or "Ingredient"),
                    stock_lot_id=lot.id,
                    movement_type=KitchenMovementType.RESERVE_FOR_PLAN,
                    quantity=reserved_quantity,
                    base_quantity=reserved_quantity,
                    unit=unit,
                    base_unit=lot.base_unit,
                    reference_type="saved_plan",
                    reference_id=saved_plan_id,
                    note="Reserved for saved meal plan.",
                    metadata={
                        "meal_id": str(demand.get("meal_id") or ""),
                        "slot": str(demand.get("slot") or ""),
                        "effective_date": effective_date.isoformat() if effective_date is not None else None,
                    },
                )
                allocations_to_create.append(
                    {
                        "user_id": user_id,
                        "saved_plan_id": saved_plan_id,
                        "effective_date": effective_date.isoformat() if effective_date is not None else None,
                        "slot": str(demand.get("slot") or ""),
                        "meal_id": str(demand.get("meal_id") or ""),
                        "product_id": product_id,
                        "product_name": str(demand.get("product_name") or lot.product_name or "Ingredient"),
                        "stock_lot_id": lot.id,
                        "required_quantity": float(demand.get("required_quantity") or 0.0),
                        "reserved_quantity": reserved_quantity,
                        "consumed_quantity": 0.0,
                        "unit": unit,
                        "base_unit": lot.base_unit,
                        "base_required_quantity": float(demand.get("required_quantity") or 0.0),
                        "base_reserved_quantity": reserved_quantity,
                        "base_consumed_quantity": 0.0,
                        "metadata": {
                            "meal_name": str(demand.get("meal_name") or ""),
                        },
                    }
                )
                required_quantity -= reserved_quantity
                if required_quantity <= 0:
                    break

        self._kitchen_repository.create_allocations(allocations=allocations_to_create)
        self._sync_pantry_projection(user_id)

    def release_saved_plan_allocations(
        self,
        *,
        user_id: str,
        saved_plan_id: str,
        effective_date: date | None = None,
        slot: str | None = None,
        meal_id: str | None = None,
    ) -> None:
        allocations = self._kitchen_repository.delete_allocations_for_saved_plan(
            user_id=user_id,
            saved_plan_id=saved_plan_id,
            slot=slot,
            effective_date=effective_date,
            meal_id=meal_id,
            status=KitchenAllocationStatus.RESERVED,
        )
        for allocation in allocations:
            lot = next(
                (
                    item
                    for item in self._kitchen_repository.list_stock_lots(
                        user_id=user_id,
                        product_id=allocation.product_id,
                    )
                    if item.id == allocation.stock_lot_id
                ),
                None,
            )
            if lot is None:
                continue
            self._kitchen_repository.update_stock_lot_quantities(
                stock_lot_id=lot.id,
                quantity_reserved=max(lot.quantity_reserved - allocation.reserved_quantity, 0.0),
                base_quantity_reserved=max(lot.base_quantity_reserved - allocation.base_reserved_quantity, 0.0),
            )
            self._kitchen_repository.create_movement(
                user_id=user_id,
                product_id=allocation.product_id,
                product_name=allocation.product_name,
                stock_lot_id=allocation.stock_lot_id,
                movement_type=KitchenMovementType.RELEASE_RESERVATION,
                quantity=allocation.reserved_quantity,
                base_quantity=allocation.base_reserved_quantity,
                unit=allocation.unit,
                base_unit=allocation.base_unit,
                reference_type="saved_plan",
                reference_id=saved_plan_id,
                note="Released saved meal plan reservation.",
                metadata={
                    "meal_id": allocation.meal_id,
                    "slot": allocation.slot,
                    "effective_date": allocation.effective_date.isoformat() if allocation.effective_date else None,
                },
            )
        self._sync_pantry_projection(user_id)

    def consume_saved_plan_slot(
        self,
        *,
        current_user: User,
        saved_plan_id: str,
        payload: SavedPlanKitchenConsumeRequest,
    ) -> SavedPlanKitchenResponse:
        allocations = self._kitchen_repository.list_allocations_for_saved_plan(
            user_id=current_user.id,
            saved_plan_id=saved_plan_id,
            slot=payload.slot,
            effective_date=payload.effective_date,
            status=KitchenAllocationStatus.RESERVED,
        )
        if payload.meal_id is not None:
            allocations = [item for item in allocations if item.meal_id == payload.meal_id]

        lots_by_id = {
            lot.id: lot
            for lot in self._kitchen_repository.list_stock_lots(user_id=current_user.id)
        }

        for allocation in allocations:
            lot = lots_by_id.get(allocation.stock_lot_id)
            if lot is None:
                continue
            self._kitchen_repository.update_stock_lot_quantities(
                stock_lot_id=lot.id,
                quantity_reserved=max(lot.quantity_reserved - allocation.reserved_quantity, 0.0),
                quantity_consumed=lot.quantity_consumed + allocation.reserved_quantity,
                base_quantity_reserved=max(lot.base_quantity_reserved - allocation.base_reserved_quantity, 0.0),
                base_quantity_consumed=lot.base_quantity_consumed + allocation.base_reserved_quantity,
            )
            self._kitchen_repository.replace_allocation_status(
                allocation_id=allocation.id,
                status=KitchenAllocationStatus.CONSUMED,
                consumed_quantity=allocation.reserved_quantity,
                base_consumed_quantity=allocation.base_reserved_quantity,
            )
            self._kitchen_repository.create_movement(
                user_id=current_user.id,
                product_id=allocation.product_id,
                product_name=allocation.product_name,
                stock_lot_id=allocation.stock_lot_id,
                movement_type=KitchenMovementType.CONSUME_FOR_MEAL,
                quantity=allocation.reserved_quantity,
                base_quantity=allocation.base_reserved_quantity,
                unit=allocation.unit,
                base_unit=allocation.base_unit,
                reference_type="saved_plan",
                reference_id=saved_plan_id,
                note="Consumed for completed meal.",
                metadata={
                    "meal_id": allocation.meal_id,
                    "slot": allocation.slot,
                    "effective_date": allocation.effective_date.isoformat() if allocation.effective_date else None,
                },
            )

        self._sync_pantry_projection(current_user.id)
        return self.list_saved_plan_allocations(
            current_user=current_user,
            saved_plan_id=saved_plan_id,
        )

    def list_saved_plan_allocations(
        self,
        *,
        current_user: User,
        saved_plan_id: str,
    ) -> SavedPlanKitchenResponse:
        allocations = self._kitchen_repository.list_allocations_for_saved_plan(
            user_id=current_user.id,
            saved_plan_id=saved_plan_id,
        )
        return SavedPlanKitchenResponse(
            items=[
                SavedPlanKitchenAllocationResponse(
                    id=item.id,
                    saved_plan_id=item.saved_plan_id,
                    effective_date=item.effective_date,
                    slot=item.slot,
                    meal_id=item.meal_id,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    reserved_quantity=item.reserved_quantity,
                    consumed_quantity=item.consumed_quantity,
                    unit=item.unit,
                    status=item.status.value,
                    updated_at=item.updated_at,
                )
                for item in allocations
            ]
        )

    def preview_order_import(
        self,
        *,
        current_user: User,
        order_id: str,
    ) -> KitchenOrderImportPreviewResponse:
        order = self._get_user_order(current_user=current_user, order_id=order_id)
        items: list[KitchenOrderImportPreviewItemResponse] = []
        importable_count = 0
        already_imported_count = 0
        for item in order.items:
            existing = self._kitchen_repository.get_order_stock_lot(
                user_id=current_user.id,
                source_id=item.id,
            )
            already_imported = existing is not None
            will_import = order.status == OrderStatus.DELIVERED and not already_imported
            if will_import:
                importable_count += 1
            if already_imported:
                already_imported_count += 1
            items.append(
                KitchenOrderImportPreviewItemResponse(
                    item_id=item.id,
                    product_id=item.product_id,
                    product_name=item.product_name,
                    quantity=float(item.quantity),
                    unit=item.unit_label,
                    will_import=will_import,
                    already_imported=already_imported,
                )
            )
        return KitchenOrderImportPreviewResponse(
            order_id=order.id,
            order_status=order.status.value,
            items=items,
            importable_count=importable_count,
            already_imported_count=already_imported_count,
        )

    def import_order_to_kitchen(
        self,
        *,
        current_user: User,
        order_id: str,
    ) -> KitchenOrderImportResponse:
        order = self._get_user_order(current_user=current_user, order_id=order_id)
        if order.status != OrderStatus.DELIVERED:
            raise KitchenOrderImportError("Only delivered grocery orders can be added to Kitchen.")

        imported_count = 0
        skipped_count = 0
        delivered_at = order.updated_at if order.updated_at <= datetime.now(timezone.utc) else datetime.now(timezone.utc)
        for item in order.items:
            existing = self._kitchen_repository.get_order_stock_lot(
                user_id=current_user.id,
                source_id=item.id,
            )
            if existing is not None:
                skipped_count += 1
                continue
            lot = self._kitchen_repository.create_order_stock_lot(
                user_id=current_user.id,
                product_id=item.product_id,
                product_name=item.product_name,
                source_id=item.id,
                quantity_on_hand=float(item.quantity),
                unit=item.unit_label,
                base_unit=item.unit_label,
                base_quantity_on_hand=float(item.quantity),
                country_code=None,
                delivered_at=delivered_at,
                metadata={
                    "order_id": order.id,
                    "order_number": order.order_number,
                },
            )
            self._kitchen_repository.create_movement(
                user_id=current_user.id,
                product_id=item.product_id,
                product_name=item.product_name,
                stock_lot_id=lot.id,
                movement_type=KitchenMovementType.DELIVERY_IMPORT,
                quantity=float(item.quantity),
                base_quantity=float(item.quantity),
                unit=item.unit_label,
                base_unit=item.unit_label,
                reference_type="order",
                reference_id=order.id,
                note="Imported from delivered grocery order.",
                metadata={"order_item_id": item.id},
            )
            imported_count += 1

        self._sync_pantry_projection(current_user.id)
        return KitchenOrderImportResponse(
            order_id=order.id,
            imported_count=imported_count,
            skipped_count=skipped_count,
            message=(
                "Kitchen updated from delivered groceries."
                if imported_count > 0
                else "No new delivered groceries were added to Kitchen."
            ),
        )

    def _get_user_order(self, *, current_user: User, order_id: str) -> Order:
        order = self._order_repository.get_order_for_user(
            user_id=current_user.id,
            order_id=order_id,
        )
        if order is None:
            raise KitchenOrderImportError("Order not found.")
        return order

    def _response_for_product(self, *, user_id: str, product_id: str) -> KitchenItemResponse:
        item = next(
            (
                projected
                for projected in self._projected_items(user_id=user_id)
                if projected.product_id == product_id
            ),
            None,
        )
        if item is None:
            now = datetime.now(timezone.utc)
            item = _ProjectedKitchenItem(
                product_id=product_id,
                product_name="",
                unit="",
                base_unit="",
                country_code=None,
                quantity_on_hand=0.0,
                quantity_reserved=0.0,
                quantity_consumed=0.0,
                quantity_available=0.0,
                source_types=[],
                updated_at=now,
            )
        return self._to_item_response(item)

    def _to_item_response(self, item: _ProjectedKitchenItem) -> KitchenItemResponse:
        return KitchenItemResponse(
            product_id=item.product_id,
            product_name=item.product_name,
            quantity_on_hand=round(item.quantity_on_hand, 2),
            quantity_reserved=round(item.quantity_reserved, 2),
            quantity_available=round(item.quantity_available, 2),
            quantity_consumed=round(item.quantity_consumed, 2),
            unit=item.unit,
            base_unit=item.base_unit,
            country_code=item.country_code,
            source_types=item.source_types,
            updated_at=item.updated_at,
        )

    def _projected_items(
        self,
        *,
        user_id: str,
        include_saved_plan_id: str | None = None,
    ) -> list[_ProjectedKitchenItem]:
        lots = self._kitchen_repository.list_stock_lots(user_id=user_id)
        reserved_back_by_product: dict[tuple[str, str], float] = defaultdict(float)
        if include_saved_plan_id:
            for allocation in self._kitchen_repository.list_allocations_for_saved_plan(
                user_id=user_id,
                saved_plan_id=include_saved_plan_id,
                status=KitchenAllocationStatus.RESERVED,
            ):
                reserved_back_by_product[(allocation.product_id, allocation.unit)] += allocation.reserved_quantity

        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for lot in lots:
            key = (lot.product_id, lot.unit)
            item = grouped.setdefault(
                key,
                {
                    "product_id": lot.product_id,
                    "product_name": lot.product_name,
                    "unit": lot.unit,
                    "base_unit": lot.base_unit,
                    "country_code": lot.country_code.value if lot.country_code is not None else None,
                    "quantity_on_hand": 0.0,
                    "quantity_reserved": 0.0,
                    "quantity_consumed": 0.0,
                    "quantity_available": 0.0,
                    "source_types": set(),
                    "updated_at": lot.updated_at,
                },
            )
            free_quantity = max(lot.quantity_on_hand - lot.quantity_reserved - lot.quantity_consumed, 0.0)
            item["quantity_on_hand"] += lot.quantity_on_hand
            item["quantity_reserved"] += lot.quantity_reserved
            item["quantity_consumed"] += lot.quantity_consumed
            item["quantity_available"] += free_quantity
            item["source_types"].add(lot.source_type.value)
            if lot.updated_at > item["updated_at"]:
                item["updated_at"] = lot.updated_at

        for key, quantity in reserved_back_by_product.items():
            if key in grouped:
                grouped[key]["quantity_available"] += quantity

        return [
            _ProjectedKitchenItem(
                product_id=item["product_id"],
                product_name=item["product_name"],
                unit=item["unit"],
                base_unit=item["base_unit"],
                country_code=item["country_code"],
                quantity_on_hand=float(item["quantity_on_hand"]),
                quantity_reserved=float(item["quantity_reserved"]),
                quantity_consumed=float(item["quantity_consumed"]),
                quantity_available=float(item["quantity_available"]),
                source_types=sorted(item["source_types"]),
                updated_at=item["updated_at"],
            )
            for item in sorted(
                grouped.values(),
                key=lambda value: (value["product_name"].lower(), value["product_id"]),
            )
        ]

    def _sync_pantry_projection(self, user_id: str) -> None:
        projected_items = self._projected_items(user_id=user_id)
        replacement_items = [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": max(item.quantity_available, 0.0),
                "unit": item.unit,
                "country_code": item.country_code,
            }
            for item in projected_items
            if item.quantity_available > 0 and item.unit
        ]
        self._user_pantry_repository.replace_items(
            user_id=user_id,
            items=replacement_items,
        )

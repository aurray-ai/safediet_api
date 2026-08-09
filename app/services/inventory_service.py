import re
from dataclasses import dataclass

from app.models.grocery import CountryCode, GroceryProduct
from app.models.inventory import DeliveryFeeRule, InventoryAdjustment, InventoryItem
from app.repositories.grocery_repository import GroceryRepository
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.inventory import (
    AdminInventoryAdjustmentListResponse,
    AdminInventoryAdjustmentRequest,
    AdminInventoryAdjustmentResponse,
    AdminInventoryItemResponse,
    AdminInventoryItemUpsertRequest,
    AdminInventoryListResponse,
    DeliveryFeeRuleCreateRequest,
    DeliveryFeeRuleListResponse,
    DeliveryFeeRuleResponse,
    DeliveryFeeRuleUpdateRequest,
)
from app.services.pricing import apply_category_discount


class InventoryNotFoundError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedMemberPrice:
    base_price_minor: int
    unit_price_minor: int
    discount_percent_applied: float


class InventoryService:
    _default_seed_available_quantity = 100
    _default_seed_reserved_quantity = 0
    _default_seed_max_per_order = 25
    _default_seed_unit_weight_grams = 500

    def __init__(
        self,
        *,
        inventory_repository: InventoryRepository,
        grocery_repository: GroceryRepository,
        default_store_id: str,
    ) -> None:
        self._inventory_repository = inventory_repository
        self._grocery_repository = grocery_repository
        self._default_store_id = default_store_id

    def ensure_seed_inventory_defaults(self) -> None:
        page = 1
        page_size = 250

        while True:
            products, total = self._grocery_repository.list_all_products(
                page=page,
                page_size=page_size,
            )
            if not products:
                break

            for product in products:
                self.ensure_sellable_inventory_item(
                    product_id=product.id,
                    store_id=self._default_store_id,
                )

            if page * page_size >= total:
                break
            page += 1

    def ensure_sellable_inventory_item(
        self,
        *,
        product_id: str,
        store_id: str | None = None,
    ) -> InventoryItem | None:
        resolved_store_id = store_id or self._default_store_id
        product = self._grocery_repository.get_product_by_id(product_id)
        if product is None or not product.is_active:
            return None

        existing = self._inventory_repository.get_by_product_id(
            store_id=resolved_store_id,
            product_id=product_id,
        )
        if existing is not None:
            return existing

        return self._create_default_inventory_item(
            product=product,
            store_id=resolved_store_id,
        )

    def list_inventory(
        self,
        *,
        page: int,
        page_size: int,
        search: str | None,
        is_active: bool | None,
    ) -> AdminInventoryListResponse:
        items, total = self._inventory_repository.list_inventory(
            store_id=self._default_store_id,
            page=page,
            page_size=page_size,
            search=search,
            is_active=is_active,
        )
        return AdminInventoryListResponse(
            items=[self._to_inventory_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def upsert_inventory_item(
        self,
        *,
        product_id: str,
        payload: AdminInventoryItemUpsertRequest,
    ) -> AdminInventoryItemResponse:
        if self._grocery_repository.get_product_by_id(product_id) is None:
            raise InventoryNotFoundError
        item = self._inventory_repository.upsert_inventory_item(
            store_id=self._default_store_id,
            product_id=product_id,
            sku=payload.sku,
            is_active=payload.is_active,
            available_quantity=payload.available_quantity,
            reserved_quantity=payload.reserved_quantity,
            unit_label=payload.unit_label,
            unit_weight_grams=payload.unit_weight_grams,
            max_per_order=payload.max_per_order,
            allow_substitutions=payload.allow_substitutions,
            substitution_group=payload.substitution_group,
        )
        return self._to_inventory_response(item)

    def get_inventory_item(self, *, product_id: str) -> AdminInventoryItemResponse:
        item = self._inventory_repository.get_by_product_id(
            store_id=self._default_store_id,
            product_id=product_id,
        )
        if item is None:
            raise InventoryNotFoundError
        return self._to_inventory_response(item)

    def adjust_inventory(
        self,
        *,
        product_id: str,
        actor_user_id: str | None,
        payload: AdminInventoryAdjustmentRequest,
    ) -> AdminInventoryAdjustmentResponse:
        item = self._inventory_repository.get_by_product_id(
            store_id=self._default_store_id,
            product_id=product_id,
        )
        if item is None:
            raise InventoryNotFoundError
        if payload.adjustment_type.value.endswith("increment"):
            updated = self._inventory_repository.increment_available(
                store_id=item.store_id,
                product_id=product_id,
                quantity=payload.quantity,
            )
            delta = payload.quantity
        elif payload.adjustment_type.value.endswith("decrement"):
            updated = self._inventory_repository.decrement_available(
                store_id=item.store_id,
                product_id=product_id,
                quantity=payload.quantity,
            )
            delta = -payload.quantity
        else:
            desired = payload.quantity
            delta = desired - item.available_quantity
            self._inventory_repository.upsert_inventory_item(
                store_id=item.store_id,
                product_id=item.product_id,
                sku=item.sku,
                is_active=item.is_active,
                available_quantity=desired,
                reserved_quantity=item.reserved_quantity,
                unit_label=item.unit_label,
                unit_weight_grams=item.unit_weight_grams,
                max_per_order=item.max_per_order,
                allow_substitutions=item.allow_substitutions,
                substitution_group=item.substitution_group,
            )
            updated = self._inventory_repository.get_by_product_id(store_id=item.store_id, product_id=product_id)
            if updated is None:
                raise RuntimeError("Inventory item missing after adjustment.")
        adjustment = self._inventory_repository.apply_adjustment(
            inventory_item_id=updated.id,
            product_id=updated.product_id,
            store_id=updated.store_id,
            adjustment_type=payload.adjustment_type,
            delta_quantity=delta,
            reason=payload.reason,
            actor_user_id=actor_user_id,
            reference_type=payload.reference_type,
            reference_id=payload.reference_id,
            metadata=payload.metadata,
        )
        return self._to_adjustment_response(adjustment)

    def list_adjustments(
        self,
        *,
        product_id: str,
        page: int,
        page_size: int,
    ) -> AdminInventoryAdjustmentListResponse:
        items, total = self._inventory_repository.list_adjustments(
            product_id=product_id,
            page=page,
            page_size=page_size,
        )
        return AdminInventoryAdjustmentListResponse(
            items=[self._to_adjustment_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def list_delivery_fee_rules(self, *, currency: str | None) -> DeliveryFeeRuleListResponse:
        items = self._inventory_repository.list_delivery_fee_rules(
            store_id=self._default_store_id,
            currency=currency,
        )
        return DeliveryFeeRuleListResponse(items=[self._to_delivery_fee_rule_response(item) for item in items])

    def create_delivery_fee_rule(self, *, payload: DeliveryFeeRuleCreateRequest) -> DeliveryFeeRuleResponse:
        item = self._inventory_repository.create_delivery_fee_rule(
            store_id=self._default_store_id,
            currency=payload.currency,
            min_weight_grams=payload.min_weight_grams,
            max_weight_grams=payload.max_weight_grams,
            fee_minor=payload.fee_minor,
            is_active=payload.is_active,
        )
        return self._to_delivery_fee_rule_response(item)

    def update_delivery_fee_rule(
        self,
        *,
        rule_id: str,
        payload: DeliveryFeeRuleUpdateRequest,
    ) -> DeliveryFeeRuleResponse:
        item = self._inventory_repository.update_delivery_fee_rule(
            rule_id=rule_id,
            payload=payload.model_dump(),
        )
        if item is None:
            raise InventoryNotFoundError
        return self._to_delivery_fee_rule_response(item)

    def resolve_unit_price_minor(
        self,
        *,
        product: GroceryProduct,
        currency: str,
    ) -> int:
        active_prices = [price for price in product.prices if price.is_active]
        for price in active_prices:
            if price.currency_code.value == currency:
                return int(round(price.amount * 100))
        if active_prices:
            return int(round(active_prices[0].amount * 100))
        return 0

    def resolve_member_unit_price_minor(
        self,
        *,
        product: GroceryProduct,
        currency: str,
        is_subscriber: bool,
    ) -> ResolvedMemberPrice:
        base_price_minor = self.resolve_unit_price_minor(product=product, currency=currency)

        discount_percent = None
        if is_subscriber:
            category = self._grocery_repository.get_category(product.category_id)
            if category is not None:
                discount_percent = category.discount_percent

        unit_price_minor, discount_percent_applied = apply_category_discount(base_price_minor, discount_percent)
        return ResolvedMemberPrice(
            base_price_minor=base_price_minor,
            unit_price_minor=unit_price_minor,
            discount_percent_applied=discount_percent_applied,
        )

    def resolve_weight_based_delivery_fee(
        self,
        *,
        total_weight_grams: int,
        currency: str,
        store_id: str | None = None,
    ) -> int:
        rules = self._inventory_repository.list_delivery_fee_rules(
            store_id=store_id or self._default_store_id,
            currency=currency,
        )
        for rule in rules:
            if not rule.is_active:
                continue
            if total_weight_grams >= rule.min_weight_grams and total_weight_grams < rule.max_weight_grams:
                return rule.fee_minor
        return 0

    def validate_sellable_items(
        self,
        *,
        product_ids: list[str],
        country: CountryCode | None,
        store_id: str | None = None,
    ) -> dict[str, object]:
        resolved_store = store_id or self._default_store_id
        items: list[dict[str, object]] = []
        for product_id in product_ids:
            product = self._grocery_repository.get_product(product_id)
            inventory = self._inventory_repository.get_by_product_id(store_id=resolved_store, product_id=product_id)
            unit_price_minor = 0
            if product is not None:
                currency = (
                    product.prices[0].currency_code.value
                    if product.prices
                    else "GBP"
                )
                if country is not None:
                    for price in product.prices:
                        if price.is_active and price.country_code == country:
                            currency = price.currency_code.value
                            break
                unit_price_minor = self.resolve_unit_price_minor(product=product, currency=currency)
            items.append(
                {
                    "product_id": product_id,
                    "exists": product is not None,
                    "inventory_exists": inventory is not None,
                    "available_quantity": inventory.available_quantity if inventory is not None else 0,
                    "allow_substitutions": inventory.allow_substitutions if inventory is not None else False,
                    "unit_price_minor": unit_price_minor,
                }
            )
        return {"store_id": resolved_store, "items": items}

    def _to_inventory_response(self, item: InventoryItem) -> AdminInventoryItemResponse:
        product = self._grocery_repository.get_product_by_id(item.product_id)
        return AdminInventoryItemResponse(
            id=item.id,
            store_id=item.store_id,
            product_id=item.product_id,
            product_name=product.product if product is not None else None,
            category_id=product.category_id if product is not None else None,
            img_url=product.img_url if product is not None else None,
            sku=item.sku,
            is_active=item.is_active,
            available_quantity=item.available_quantity,
            reserved_quantity=item.reserved_quantity,
            unit_label=item.unit_label,
            unit_weight_grams=item.unit_weight_grams,
            max_per_order=item.max_per_order,
            allow_substitutions=item.allow_substitutions,
            substitution_group=item.substitution_group,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    def _create_default_inventory_item(
        self,
        *,
        product: GroceryProduct,
        store_id: str,
    ) -> InventoryItem:
        unit_label = self._seed_unit_label(product)
        return self._inventory_repository.upsert_inventory_item(
            store_id=store_id,
            product_id=product.id,
            sku=product.id.upper(),
            is_active=True,
            available_quantity=self._default_seed_available_quantity,
            reserved_quantity=self._default_seed_reserved_quantity,
            unit_label=unit_label,
            unit_weight_grams=self._seed_unit_weight_grams(unit_label),
            max_per_order=self._default_seed_max_per_order,
            allow_substitutions=True,
            substitution_group=product.category_id,
        )

    @staticmethod
    def _seed_unit_label(product: GroceryProduct) -> str:
        active_price = next((price for price in product.prices if price.is_active), None)
        return active_price.price_unit if active_price is not None else "1 item"

    @classmethod
    def _seed_unit_weight_grams(cls, unit_label: str) -> int:
        normalized = unit_label.strip().lower()
        match = re.match(r"^(?P<amount>\d+(?:\.\d+)?)\s*(?P<unit>kg|g|l|ml)\b", normalized)
        if match is None:
            return cls._default_seed_unit_weight_grams

        amount = float(match.group("amount"))
        unit = match.group("unit")
        if unit == "kg":
            return max(1, int(round(amount * 1000)))
        if unit == "g":
            return max(1, int(round(amount)))
        if unit == "l":
            return max(1, int(round(amount * 1000)))
        if unit == "ml":
            return max(1, int(round(amount)))
        return cls._default_seed_unit_weight_grams

    @staticmethod
    def _to_adjustment_response(item: InventoryAdjustment) -> AdminInventoryAdjustmentResponse:
        return AdminInventoryAdjustmentResponse(
            id=item.id,
            inventory_item_id=item.inventory_item_id,
            product_id=item.product_id,
            store_id=item.store_id,
            adjustment_type=item.adjustment_type,
            delta_quantity=item.delta_quantity,
            reason=item.reason,
            actor_user_id=item.actor_user_id,
            reference_type=item.reference_type,
            reference_id=item.reference_id,
            metadata=item.metadata,
            created_at=item.created_at,
        )

    @staticmethod
    def _to_delivery_fee_rule_response(item: DeliveryFeeRule) -> DeliveryFeeRuleResponse:
        return DeliveryFeeRuleResponse(
            id=item.id,
            store_id=item.store_id,
            currency=item.currency,
            min_weight_grams=item.min_weight_grams,
            max_weight_grams=item.max_weight_grams,
            fee_minor=item.fee_minor,
            is_active=item.is_active,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

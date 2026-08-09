from app.models.user import User
from app.schemas.kitchen import KitchenItemUpsertRequest
from app.schemas.user_pantry import (
    UserPantryItemResponse,
    UserPantryItemUpsertRequest,
    UserPantryListResponse,
)
from app.services.kitchen_service import KitchenService


class UserPantryService:
    def __init__(self, kitchen_service: KitchenService) -> None:
        self._kitchen_service = kitchen_service

    def list_items(self, *, current_user: User) -> UserPantryListResponse:
        kitchen_items = self._kitchen_service.list_items(current_user=current_user).items
        return UserPantryListResponse(
            items=[
                UserPantryItemResponse(
                    id=f"kitchen:{item.product_id}",
                    product_id=item.product_id,
                    product_name=item.product_name,
                    quantity=item.quantity_available,
                    unit=item.unit,
                    country_code=item.country_code,
                    created_at=item.updated_at,
                    updated_at=item.updated_at,
                )
                for item in kitchen_items
                if item.quantity_available > 0
            ]
        )

    def upsert_item(
        self,
        *,
        current_user: User,
        payload: UserPantryItemUpsertRequest,
    ) -> UserPantryItemResponse:
        item = self._kitchen_service.upsert_manual_item(
            current_user=current_user,
            payload=KitchenItemUpsertRequest(
                product_id=payload.product_id,
                product_name=payload.product_name,
                quantity=payload.quantity,
                unit=payload.unit,
                country_code=payload.country_code,
            ),
        )
        return UserPantryItemResponse(
            id=f"kitchen:{item.product_id}",
            product_id=item.product_id,
            product_name=item.product_name,
            quantity=item.quantity_available,
            unit=item.unit,
            country_code=item.country_code,
            created_at=item.updated_at,
            updated_at=item.updated_at,
        )

    def delete_item(self, *, current_user: User, product_id: str) -> bool:
        return self._kitchen_service.delete_manual_item(
            current_user=current_user,
            product_id=product_id,
        )

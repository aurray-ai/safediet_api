from app.models.address import UserDeliveryAddress
from app.models.user import User
from app.repositories.address_repository import AddressRepository
from app.schemas.address import (
    UserDeliveryAddressCreateRequest,
    UserDeliveryAddressListResponse,
    UserDeliveryAddressResponse,
    UserDeliveryAddressUpdateRequest,
)


class AddressNotFoundError(Exception):
    pass


class AddressService:
    def __init__(self, address_repository: AddressRepository) -> None:
        self._address_repository = address_repository

    def list_addresses(self, *, current_user: User) -> UserDeliveryAddressListResponse:
        items = self._address_repository.list_for_user(user_id=current_user.id)
        return UserDeliveryAddressListResponse(items=[self._to_response(item) for item in items])

    def create_address(
        self,
        *,
        current_user: User,
        payload: UserDeliveryAddressCreateRequest,
    ) -> UserDeliveryAddressResponse:
        item = self._address_repository.create_for_user(
            user_id=current_user.id,
            label=payload.label,
            recipient_name=payload.recipient_name,
            phone_number=payload.phone_number,
            line1=payload.line1,
            line2=payload.line2,
            city=payload.city,
            state=payload.state,
            postal_code=payload.postal_code,
            country=payload.country,
            delivery_notes=payload.delivery_notes,
            is_default=payload.is_default,
        )
        return self._to_response(item)

    def update_address(
        self,
        *,
        current_user: User,
        address_id: str,
        payload: UserDeliveryAddressUpdateRequest,
    ) -> UserDeliveryAddressResponse:
        item = self._address_repository.update_for_user(
            user_id=current_user.id,
            address_id=address_id,
            payload=payload.model_dump(),
        )
        if item is None:
            raise AddressNotFoundError
        return self._to_response(item)

    def delete_address(self, *, current_user: User, address_id: str) -> bool:
        return self._address_repository.delete_for_user(user_id=current_user.id, address_id=address_id)

    def set_default_address(self, *, current_user: User, address_id: str) -> UserDeliveryAddressResponse:
        item = self._address_repository.set_default(user_id=current_user.id, address_id=address_id)
        if item is None:
            raise AddressNotFoundError
        return self._to_response(item)

    @staticmethod
    def _to_response(item: UserDeliveryAddress) -> UserDeliveryAddressResponse:
        return UserDeliveryAddressResponse(
            id=item.id,
            label=item.label,
            recipient_name=item.recipient_name,
            phone_number=item.phone_number,
            line1=item.line1,
            line2=item.line2,
            city=item.city,
            state=item.state,
            postal_code=item.postal_code,
            country=item.country,
            delivery_notes=item.delivery_notes,
            is_default=item.is_default,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

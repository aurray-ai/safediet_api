from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies import get_address_service, get_current_user
from app.models.user import User
from app.schemas.address import (
    SelectDefaultAddressRequest,
    UserDeliveryAddressCreateRequest,
    UserDeliveryAddressListResponse,
    UserDeliveryAddressResponse,
    UserDeliveryAddressUpdateRequest,
)
from app.services.address_service import AddressNotFoundError, AddressService

router = APIRouter(prefix="/addresses", tags=["addresses"])


@router.get("", response_model=UserDeliveryAddressListResponse, status_code=status.HTTP_200_OK)
def list_addresses(
    current_user: User = Depends(get_current_user),
    address_service: AddressService = Depends(get_address_service),
) -> UserDeliveryAddressListResponse:
    return address_service.list_addresses(current_user=current_user)


@router.post("", response_model=UserDeliveryAddressResponse, status_code=status.HTTP_201_CREATED)
def create_address(
    payload: UserDeliveryAddressCreateRequest,
    current_user: User = Depends(get_current_user),
    address_service: AddressService = Depends(get_address_service),
) -> UserDeliveryAddressResponse:
    return address_service.create_address(current_user=current_user, payload=payload)


@router.put("/{address_id}", response_model=UserDeliveryAddressResponse, status_code=status.HTTP_200_OK)
def update_address(
    address_id: str,
    payload: UserDeliveryAddressUpdateRequest,
    current_user: User = Depends(get_current_user),
    address_service: AddressService = Depends(get_address_service),
) -> UserDeliveryAddressResponse:
    try:
        return address_service.update_address(current_user=current_user, address_id=address_id, payload=payload)
    except AddressNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.") from exc


@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(
    address_id: str,
    current_user: User = Depends(get_current_user),
    address_service: AddressService = Depends(get_address_service),
) -> Response:
    deleted = address_service.delete_address(current_user=current_user, address_id=address_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{address_id}/default", response_model=UserDeliveryAddressResponse, status_code=status.HTTP_200_OK)
def set_default_address(
    address_id: str,
    _: SelectDefaultAddressRequest | None = None,
    current_user: User = Depends(get_current_user),
    address_service: AddressService = Depends(get_address_service),
) -> UserDeliveryAddressResponse:
    try:
        return address_service.set_default_address(current_user=current_user, address_id=address_id)
    except AddressNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found.") from exc

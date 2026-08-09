from fastapi import APIRouter, Depends, status

from app.dependencies import get_current_user, get_push_device_service
from app.models.user import User
from app.schemas.push_device import (
    PushDeviceResponse,
    RegisterPushDeviceRequest,
    UnregisterPushDeviceRequest,
    UnregisterPushDeviceResponse,
)
from app.services.push_device_service import PushDeviceService

router = APIRouter(prefix="/push-devices", tags=["push-devices"])


@router.post("", response_model=PushDeviceResponse, status_code=status.HTTP_201_CREATED)
def register_push_device(
    payload: RegisterPushDeviceRequest,
    current_user: User = Depends(get_current_user),
    push_device_service: PushDeviceService = Depends(get_push_device_service),
) -> PushDeviceResponse:
    device = push_device_service.register_device(
        current_user=current_user,
        platform=payload.platform,
        device_token=payload.device_token,
        environment=payload.environment,
        locations=payload.locations,
        delivery_types=payload.delivery_types,
        app_version=payload.app_version,
        build_number=payload.build_number,
        device_name=payload.device_name,
    )
    return PushDeviceResponse.from_model(device)


@router.post("/unregister", response_model=UnregisterPushDeviceResponse, status_code=status.HTTP_200_OK)
def unregister_push_device(
    payload: UnregisterPushDeviceRequest,
    current_user: User = Depends(get_current_user),
    push_device_service: PushDeviceService = Depends(get_push_device_service),
) -> UnregisterPushDeviceResponse:
    push_device_service.unregister_device(
        current_user=current_user,
        platform=payload.platform,
        device_token=payload.device_token,
    )
    return UnregisterPushDeviceResponse()

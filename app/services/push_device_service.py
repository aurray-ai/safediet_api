from dataclasses import dataclass

from app.models.push_device import PushDevice, PushEnvironment, PushPlatform
from app.models.user import User
from app.repositories.push_device_repository import PushDeviceRepository


@dataclass(frozen=True, slots=True)
class PushDeviceService:
    push_device_repository: PushDeviceRepository

    def register_device(
        self,
        *,
        current_user: User,
        platform: PushPlatform,
        device_token: str,
        environment: PushEnvironment,
        locations: list[str],
        delivery_types: list[str],
        app_version: str | None,
        build_number: str | None,
        device_name: str | None,
    ) -> PushDevice:
        return self.push_device_repository.upsert_device(
            user_id=current_user.id,
            platform=platform,
            device_token=device_token,
            environment=environment,
            locations=locations,
            delivery_types=delivery_types,
            app_version=app_version,
            build_number=build_number,
            device_name=device_name,
        )

    def unregister_device(
        self,
        *,
        current_user: User,
        platform: PushPlatform,
        device_token: str,
    ) -> None:
        self.push_device_repository.deactivate_device(
            user_id=current_user.id,
            platform=platform,
            device_token=device_token,
        )

from fastapi import APIRouter, Depends, status

from app.dependencies import get_chef_fulfillment_service, get_shopper_fulfillment_service, require_platform_user
from app.models.user import User
from app.schemas.fulfillment import FulfillmentOverviewResponse, TrackOverviewResponse
from app.services.chef_fulfillment_service import ChefFulfillmentService
from app.services.shopper_fulfillment_service import ShopperFulfillmentService

router = APIRouter(prefix="/admin/fulfillment", tags=["admin-fulfillment"])


@router.get("/overview", response_model=FulfillmentOverviewResponse, status_code=status.HTTP_200_OK)
def get_fulfillment_overview(
    _: User = Depends(require_platform_user),
    chef_fulfillment_service: ChefFulfillmentService = Depends(get_chef_fulfillment_service),
    shopper_fulfillment_service: ShopperFulfillmentService = Depends(get_shopper_fulfillment_service),
) -> FulfillmentOverviewResponse:
    return FulfillmentOverviewResponse(
        chef=TrackOverviewResponse(**chef_fulfillment_service.get_overview()),
        shopper=TrackOverviewResponse(**shopper_fulfillment_service.get_overview()),
    )

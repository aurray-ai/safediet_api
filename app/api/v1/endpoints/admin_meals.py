from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.dependencies import get_admin_meal_service, get_media_storage_service, require_platform_user
from app.models.meal import MealType
from app.models.user import User
from app.schemas.admin_meal import (
    AdminMealBulkDeleteRequest,
    AdminMealBulkDeleteResponse,
    AdminMealCreateRequest,
    AdminMealListResponse,
    AdminMealMetadataResponse,
    AdminMealResponse,
    AdminMealUploadAssetResponse,
    AdminMealUploadResponse,
)
from app.services.admin_meal_service import (
    AdminMealAlreadyExistsError,
    AdminMealCategoryNotFoundError,
    AdminMealNotFoundError,
    AdminMealProductNotFoundError,
    AdminMealService,
    AdminMealValidationError,
)
from app.services.meal_catalog_embedding_service import MealCatalogEmbeddingError
from app.services.media_storage_service import MediaStorageService

router = APIRouter(prefix="/admin/meals", tags=["admin-meals"])


@router.get("/metadata", response_model=AdminMealMetadataResponse, status_code=status.HTTP_200_OK)
def get_admin_meal_metadata(
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> AdminMealMetadataResponse:
    return admin_meal_service.get_metadata()


@router.get("", response_model=AdminMealListResponse, status_code=status.HTTP_200_OK)
def list_admin_meals(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    meal_type: MealType | None = Query(default=None),
    category_id: str | None = Query(default=None, min_length=1),
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> AdminMealListResponse:
    return admin_meal_service.list_meals(
        page=page,
        page_size=page_size,
        search=search,
        meal_type=meal_type,
        category_id=category_id,
    )


@router.post("/uploads", response_model=AdminMealUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_admin_meal_assets(
    request: Request,
    files: list[UploadFile] = File(...),
    folder: str = Form(default="meals"),
    _: User = Depends(require_platform_user),
    media_storage_service: MediaStorageService = Depends(get_media_storage_service),
) -> AdminMealUploadResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one image file is required.",
        )

    try:
        items = [
            AdminMealUploadAssetResponse(
                **asdict(
                    await media_storage_service.upload_image(
                        file=file,
                        folder=folder,
                        public_base_url=str(request.base_url).rstrip("/"),
                    )
                )
            )
            for file in files
        ]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return AdminMealUploadResponse(items=items)


@router.delete("/bulk-delete", response_model=AdminMealBulkDeleteResponse, status_code=status.HTTP_200_OK)
def bulk_delete_admin_meals(
    payload: AdminMealBulkDeleteRequest,
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> AdminMealBulkDeleteResponse:
    try:
        return admin_meal_service.delete_meals(payload.meal_ids)
    except AdminMealValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/{meal_id}", response_model=AdminMealResponse, status_code=status.HTTP_200_OK)
def get_admin_meal(
    meal_id: str,
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> AdminMealResponse:
    try:
        return admin_meal_service.get_meal(meal_id)
    except AdminMealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal not found.",
        ) from exc


@router.post("", response_model=AdminMealResponse, status_code=status.HTTP_201_CREATED)
def create_admin_meal(
    payload: AdminMealCreateRequest,
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> AdminMealResponse:
    try:
        return admin_meal_service.create_meal(payload)
    except AdminMealCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal category not found.",
        ) from exc
    except AdminMealProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more linked grocery products were not found.",
        ) from exc
    except AdminMealAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A meal with this id already exists.",
        ) from exc
    except AdminMealValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except MealCatalogEmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.put("/{meal_id}", response_model=AdminMealResponse, status_code=status.HTTP_200_OK)
def update_admin_meal(
    meal_id: str,
    payload: AdminMealCreateRequest,
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> AdminMealResponse:
    try:
        return admin_meal_service.update_meal(meal_id=meal_id, payload=payload)
    except AdminMealCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal category not found.",
        ) from exc
    except AdminMealProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more linked grocery products were not found.",
        ) from exc
    except AdminMealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal not found.",
        ) from exc
    except AdminMealValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except MealCatalogEmbeddingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.delete("/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_meal(
    meal_id: str,
    _: User = Depends(require_platform_user),
    admin_meal_service: AdminMealService = Depends(get_admin_meal_service),
) -> None:
    try:
        admin_meal_service.delete_meal(meal_id)
    except AdminMealNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Meal not found.",
        ) from exc

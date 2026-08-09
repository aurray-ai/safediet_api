from dataclasses import asdict

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from app.dependencies import get_admin_grocery_service, get_media_storage_service, require_platform_user
from app.models.user import User
from app.schemas.admin_grocery import (
    AdminGroceryBulkDeleteRequest,
    AdminGroceryBulkDeleteResponse,
    AdminGroceryProductCreateRequest,
    AdminGroceryProductListResponse,
    AdminGroceryProductPayload,
    AdminGroceryProductResponse,
    AdminGroceryUploadAssetResponse,
    AdminGroceryUploadResponse,
    AdminMetadataResponse,
)
from app.services.admin_grocery_service import (
    AdminGroceryCategoryNotFoundError,
    AdminGroceryProductAlreadyExistsError,
    AdminGroceryProductNotFoundError,
    AdminGroceryService,
    AdminGroceryValidationError,
)
from app.services.media_storage_service import MediaStorageService

router = APIRouter(prefix="/admin/groceries", tags=["admin-groceries"])


@router.get("/metadata", response_model=AdminMetadataResponse, status_code=status.HTTP_200_OK)
def get_admin_metadata(
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> AdminMetadataResponse:
    return admin_grocery_service.get_metadata()


@router.get("/products", response_model=AdminGroceryProductListResponse, status_code=status.HTTP_200_OK)
def list_admin_products(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    category_id: str | None = Query(default=None, min_length=1),
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> AdminGroceryProductListResponse:
    return admin_grocery_service.list_products(
        page=page,
        page_size=page_size,
        search=search,
        category_id=category_id,
    )


@router.post("/products/uploads", response_model=AdminGroceryUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_admin_product_assets(
    request: Request,
    files: list[UploadFile] = File(...),
    folder: str = Form(default="products"),
    _: User = Depends(require_platform_user),
    media_storage_service: MediaStorageService = Depends(get_media_storage_service),
) -> AdminGroceryUploadResponse:
    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one image file is required.",
        )

    try:
        items = [
            AdminGroceryUploadAssetResponse(
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

    return AdminGroceryUploadResponse(items=items)


@router.delete("/products/bulk-delete", response_model=AdminGroceryBulkDeleteResponse, status_code=status.HTTP_200_OK)
def bulk_delete_admin_products(
    payload: AdminGroceryBulkDeleteRequest,
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> AdminGroceryBulkDeleteResponse:
    try:
        return admin_grocery_service.delete_products(payload.product_ids)
    except AdminGroceryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("/products/{product_id}", response_model=AdminGroceryProductResponse, status_code=status.HTTP_200_OK)
def get_admin_product(
    product_id: str,
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> AdminGroceryProductResponse:
    try:
        return admin_grocery_service.get_product(product_id)
    except AdminGroceryProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery product not found.",
        ) from exc


@router.post("/products", response_model=AdminGroceryProductResponse, status_code=status.HTTP_201_CREATED)
def create_admin_product(
    payload: AdminGroceryProductCreateRequest,
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> AdminGroceryProductResponse:
    try:
        return admin_grocery_service.create_product(payload)
    except AdminGroceryCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery category not found.",
        ) from exc
    except AdminGroceryProductAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A grocery product with this id already exists.",
        ) from exc
    except AdminGroceryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.put("/products/{product_id}", response_model=AdminGroceryProductResponse, status_code=status.HTTP_200_OK)
def update_admin_product(
    product_id: str,
    payload: AdminGroceryProductPayload,
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> AdminGroceryProductResponse:
    try:
        return admin_grocery_service.update_product(product_id=product_id, payload=payload)
    except AdminGroceryCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery category not found.",
        ) from exc
    except AdminGroceryProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery product not found.",
        ) from exc
    except AdminGroceryValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_product(
    product_id: str,
    _: User = Depends(require_platform_user),
    admin_grocery_service: AdminGroceryService = Depends(get_admin_grocery_service),
) -> None:
    try:
        admin_grocery_service.delete_product(product_id)
    except AdminGroceryProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery product not found.",
        ) from exc

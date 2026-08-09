from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_grocery_service
from app.models.grocery import CountryCode, CultureTag
from app.schemas.grocery import (
    CultureMetadataResponse,
    GroceryCategoryResponse,
    GroceryProductDetailResponse,
    GroceryProductListResponse,
    NutrientMetadataResponse,
)
from app.services.grocery_service import (
    GroceryCategoryNotFoundError,
    GroceryProductNotFoundError,
    GroceryService,
)

router = APIRouter(prefix="/groceries", tags=["groceries"])


@router.get("/categories", response_model=list[GroceryCategoryResponse], status_code=status.HTTP_200_OK)
def list_categories(
    grocery_service: GroceryService = Depends(get_grocery_service),
) -> list[GroceryCategoryResponse]:
    return grocery_service.list_categories()


@router.get(
    "/categories/{category_id}/products",
    response_model=GroceryProductListResponse,
    status_code=status.HTTP_200_OK,
)
def list_products_by_category(
    category_id: str,
    country: CountryCode | None = Query(default=None),
    culture: CultureTag | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    tag: str | None = Query(default=None, min_length=1),
    sort: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    grocery_service: GroceryService = Depends(get_grocery_service),
) -> GroceryProductListResponse:
    try:
        return grocery_service.list_products_by_category(
            category_id=category_id,
            country=country,
            culture=culture,
            search=search,
            product_tag=tag,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except GroceryCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery category not found.",
        ) from exc


@router.get("/products", response_model=GroceryProductListResponse, status_code=status.HTTP_200_OK)
def list_products(
    country: CountryCode | None = Query(default=None),
    culture: CultureTag | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    tag: str | None = Query(default=None, min_length=1),
    category_id: str | None = Query(default=None, min_length=1),
    sort: str | None = Query(default=None, min_length=1),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    grocery_service: GroceryService = Depends(get_grocery_service),
) -> GroceryProductListResponse:
    try:
        return grocery_service.list_products(
            country=country,
            culture=culture,
            search=search,
            product_tag=tag,
            category_id=category_id,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    except GroceryCategoryNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery category not found.",
        ) from exc


@router.get("/products/{product_id}", response_model=GroceryProductDetailResponse, status_code=status.HTTP_200_OK)
def get_product(
    product_id: str,
    grocery_service: GroceryService = Depends(get_grocery_service),
) -> GroceryProductDetailResponse:
    try:
        return grocery_service.get_product(product_id)
    except GroceryProductNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery product not found.",
        ) from exc


@router.get("/metadata/cultures", response_model=list[CultureMetadataResponse], status_code=status.HTTP_200_OK)
def list_cultures(
    grocery_service: GroceryService = Depends(get_grocery_service),
) -> list[CultureMetadataResponse]:
    return grocery_service.list_cultures()


@router.get("/metadata/nutrients", response_model=list[NutrientMetadataResponse], status_code=status.HTTP_200_OK)
def list_nutrients(
    grocery_service: GroceryService = Depends(get_grocery_service),
) -> list[NutrientMetadataResponse]:
    return grocery_service.list_nutrients()

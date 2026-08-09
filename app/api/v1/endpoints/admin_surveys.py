from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import get_survey_service, require_platform_user
from app.models.user import User
from app.schemas.survey import (
    AdminSurveyListResponse,
    AdminSurveyResponse,
    AdminSurveyResponseListResponse,
    AdminSurveyTemplateListResponse,
    SurveyAnalyticsResponse,
    SurveySubmissionResponse,
    SurveyUpsertRequest,
)
from app.services.survey_service import (
    SurveyNotFoundError,
    SurveyService,
    SurveySlugConflictError,
    SurveyValidationError,
)

router = APIRouter(prefix="/admin/surveys", tags=["admin-surveys"])


@router.get("/templates", response_model=AdminSurveyTemplateListResponse, status_code=status.HTTP_200_OK)
def list_admin_survey_templates(
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyTemplateListResponse:
    return survey_service.list_templates()


@router.get("", response_model=AdminSurveyListResponse, status_code=status.HTTP_200_OK)
def list_admin_surveys(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, min_length=1),
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyListResponse:
    return survey_service.list_surveys(page=page, page_size=page_size, search=search)


@router.post("", response_model=AdminSurveyResponse, status_code=status.HTTP_201_CREATED)
def create_admin_survey(
    payload: SurveyUpsertRequest,
    current_user: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyResponse:
    try:
        return survey_service.create_survey(owner_user_id=current_user.id, payload=payload)
    except SurveySlugConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Survey slug already exists.") from exc
    except SurveyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get("/{survey_id}", response_model=AdminSurveyResponse, status_code=status.HTTP_200_OK)
def get_admin_survey(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyResponse:
    try:
        return survey_service.get_admin_survey(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc


@router.put("/{survey_id}", response_model=AdminSurveyResponse, status_code=status.HTTP_200_OK)
def update_admin_survey(
    survey_id: str,
    payload: SurveyUpsertRequest,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyResponse:
    try:
        return survey_service.update_survey(survey_id=survey_id, payload=payload)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc
    except SurveySlugConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Survey slug already exists.") from exc
    except SurveyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_survey(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> None:
    try:
        survey_service.delete_survey(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc


@router.post("/{survey_id}/publish", response_model=AdminSurveyResponse, status_code=status.HTTP_200_OK)
def publish_admin_survey(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyResponse:
    try:
        return survey_service.publish_survey(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc
    except SurveyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{survey_id}/close", response_model=AdminSurveyResponse, status_code=status.HTTP_200_OK)
def close_admin_survey(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyResponse:
    try:
        return survey_service.close_survey(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc


@router.get("/{survey_id}/responses", response_model=AdminSurveyResponseListResponse, status_code=status.HTTP_200_OK)
def list_admin_survey_responses(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> AdminSurveyResponseListResponse:
    try:
        return survey_service.list_responses(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc


@router.get(
    "/{survey_id}/responses/{response_id}",
    response_model=SurveySubmissionResponse,
    status_code=status.HTTP_200_OK,
)
def get_admin_survey_response(
    survey_id: str,
    response_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> SurveySubmissionResponse:
    try:
        return survey_service.get_response(survey_id=survey_id, response_id=response_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey response not found.") from exc


@router.get("/{survey_id}/analytics", response_model=SurveyAnalyticsResponse, status_code=status.HTTP_200_OK)
def get_admin_survey_analytics(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> SurveyAnalyticsResponse:
    try:
        return survey_service.get_analytics(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc


@router.get("/{survey_id}/export.csv", status_code=status.HTTP_200_OK)
def export_admin_survey_responses_csv(
    survey_id: str,
    _: User = Depends(require_platform_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> Response:
    try:
        content = survey_service.export_responses_csv(survey_id)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc

    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="survey-{survey_id}-responses.csv"'},
    )

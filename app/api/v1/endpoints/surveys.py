from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_optional_current_user, get_survey_service
from app.models.user import User
from app.schemas.survey import PublicSurveyResponse, SurveyResponseSubmissionRequest, SurveySubmissionResponse
from app.services.survey_service import (
    SurveyAccessError,
    SurveyNotFoundError,
    SurveyResponseConflictError,
    SurveyService,
    SurveyValidationError,
)

router = APIRouter(prefix="/surveys", tags=["surveys"])


@router.get("/{slug}", response_model=PublicSurveyResponse, status_code=status.HTTP_200_OK)
def get_public_survey(
    slug: str,
    survey_service: SurveyService = Depends(get_survey_service),
) -> PublicSurveyResponse:
    try:
        return survey_service.get_public_survey(slug)
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc
    except SurveyAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/{slug}/responses", response_model=SurveySubmissionResponse, status_code=status.HTTP_201_CREATED)
def submit_public_survey_response(
    slug: str,
    payload: SurveyResponseSubmissionRequest,
    request: Request,
    current_user: User | None = Depends(get_optional_current_user),
    survey_service: SurveyService = Depends(get_survey_service),
) -> SurveySubmissionResponse:
    try:
        return survey_service.submit_response(
            slug=slug,
            payload=payload,
            current_user=current_user,
            request_ip=request.client.host if request.client is not None else None,
            user_agent=request.headers.get("user-agent"),
        )
    except SurveyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found.") from exc
    except SurveyAccessError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    except SurveyResponseConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except SurveyValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

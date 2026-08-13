from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_current_user, get_student_verification_service
from app.models.student_verification import StudentVerification
from app.models.user import User
from app.schemas.student_verification import (
    EligiblePlanResponse,
    StudentClaimRequest,
    StudentVerificationStartResponse,
    StudentVerificationStatusResponse,
)
from app.services.student_verification_service import (
    StudentVerificationNotClaimedError,
    StudentVerificationService,
    StudentVerificationUnknownReferenceError,
)

router = APIRouter(prefix="/student-verification", tags=["student-verification"])


def _to_response(record: StudentVerification) -> StudentVerificationStatusResponse:
    return StudentVerificationStatusResponse(
        claims_student=record.claims_student,
        status=record.status,
        verification_method=record.verification_method,
        started_at=record.started_at,
        verified_at=record.verified_at,
        expires_at=record.expires_at,
        needs_reconciliation=record.needs_reconciliation,
    )


@router.get("/status", response_model=StudentVerificationStatusResponse, status_code=status.HTTP_200_OK)
def get_status(
    current_user: User = Depends(get_current_user),
    service: StudentVerificationService = Depends(get_student_verification_service),
) -> StudentVerificationStatusResponse:
    return _to_response(service.get_status(user=current_user))


@router.get("/eligible-plan", response_model=EligiblePlanResponse, status_code=status.HTTP_200_OK)
def get_eligible_plan(
    current_user: User = Depends(get_current_user),
    service: StudentVerificationService = Depends(get_student_verification_service),
) -> EligiblePlanResponse:
    result = service.resolve_eligible_plan(user=current_user)
    return EligiblePlanResponse(
        eligibility=result.eligibility,
        plan_code=result.plan_code,
        price_minor=result.price_minor,
    )


@router.post("/claim", response_model=StudentVerificationStartResponse, status_code=status.HTTP_200_OK)
def submit_claim(
    payload: StudentClaimRequest,
    current_user: User = Depends(get_current_user),
    service: StudentVerificationService = Depends(get_student_verification_service),
) -> StudentVerificationStartResponse:
    try:
        result = service.submit_claim(
            user=current_user,
            claims_student=payload.claims_student,
            source=payload.source,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return StudentVerificationStartResponse(
        **_to_response(result.record).model_dump(),
        verification_url=result.verification_url,
    )


@router.post("/start", response_model=StudentVerificationStartResponse, status_code=status.HTTP_200_OK)
def start_verification(
    current_user: User = Depends(get_current_user),
    service: StudentVerificationService = Depends(get_student_verification_service),
) -> StudentVerificationStartResponse:
    try:
        result = service.start_verification(user=current_user)
    except StudentVerificationNotClaimedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return StudentVerificationStartResponse(
        **_to_response(result.record).model_dump(),
        verification_url=result.verification_url,
    )


@router.post(
    "/reconciliation/acknowledge",
    response_model=StudentVerificationStatusResponse,
    status_code=status.HTTP_200_OK,
)
def acknowledge_reconciliation(
    current_user: User = Depends(get_current_user),
    service: StudentVerificationService = Depends(get_student_verification_service),
) -> StudentVerificationStatusResponse:
    try:
        record = service.acknowledge_reconciliation(user=current_user)
    except StudentVerificationNotClaimedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(record)


@router.post("/webhooks/unidays", status_code=status.HTTP_200_OK)
async def unidays_webhook(
    request: Request,
    service: StudentVerificationService = Depends(get_student_verification_service),
) -> dict[str, bool]:
    raw_body = await request.body()
    signature_header = request.headers.get("X-Unidays-Signature")
    try:
        service.handle_unidays_webhook(raw_body=raw_body, signature_header=signature_header)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except StudentVerificationUnknownReferenceError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return {"received": True}

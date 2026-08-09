import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.core.security import decode_access_token
from app.dependencies import get_user_repository
from app.services.realtime_delivery_service import realtime_delivery_service

router = APIRouter(prefix="/realtime", tags=["realtime"])
logger = logging.getLogger(__name__)


def _extract_websocket_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    token = websocket.query_params.get("access_token")
    return token.strip() if token else None


@router.websocket("/ws")
async def realtime_websocket(websocket: WebSocket) -> None:
    requested_locations = websocket.query_params.get("locations") or ""
    client_host = websocket.client.host if websocket.client else "-"
    token = _extract_websocket_token(websocket)
    if not token:
        logger.warning(
            "Realtime websocket rejected missing_token client=%s locations=%s",
            client_host,
            requested_locations or "-",
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        user_id = decode_access_token(token)
    except JWTError:
        logger.warning(
            "Realtime websocket rejected invalid_token client=%s locations=%s",
            client_host,
            requested_locations or "-",
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = get_user_repository().find_by_id(user_id)
    if user is None:
        logger.warning(
            "Realtime websocket rejected unknown_user user_id=%s client=%s locations=%s",
            user_id,
            client_host,
            requested_locations or "-",
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    locations = [
        location.strip()
        for location in (websocket.query_params.get("locations") or "").split(",")
        if location.strip()
    ]
    logger.info(
        "Realtime websocket authenticated user_id=%s client=%s locations=%s",
        user.id,
        client_host,
        ",".join(locations) or "*",
    )
    await realtime_delivery_service.connect(user_id=user.id, websocket=websocket, locations=locations)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await realtime_delivery_service.disconnect(websocket)
    except Exception:
        logger.exception("Realtime websocket failed for user_id=%s", user.id)
        await realtime_delivery_service.disconnect(websocket)

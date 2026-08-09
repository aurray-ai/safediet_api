import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

# Use PBKDF2-SHA256 for new passwords.
# Keep bcrypt as a deprecated fallback so existing accounts can still log in.
password_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_context.verify(plain_password, hashed_password)


def create_access_token(subject: str) -> str:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> str:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )
    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        raise JWTError("Invalid token subject.")
    return subject


def generate_password_reset_token() -> str:
    return secrets.token_urlsafe(32)


def hash_password_reset_token(token: str) -> str:
    settings = get_settings()
    secret = settings.jwt_secret_key.get_secret_value().encode("utf-8")
    normalized = str(token or "").encode("utf-8")
    return hmac.new(secret, normalized, hashlib.sha256).hexdigest()


def generate_invitation_token() -> str:
    return secrets.token_urlsafe(32)


def hash_invitation_token(token: str) -> str:
    settings = get_settings()
    secret = settings.jwt_secret_key.get_secret_value().encode("utf-8")
    normalized = str(token or "").encode("utf-8")
    return hmac.new(secret, normalized, hashlib.sha256).hexdigest()

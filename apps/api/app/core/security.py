from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.auth import AuthRuntimeSettings, InvalidTokenError
from encodr_db.models import User


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: str
    username: str
    role: str
    expires_at: datetime


class PasswordHashService:
    def __init__(self, scheme: str) -> None:
        if scheme != "argon2id":
            raise ValueError(f"Unsupported password hash scheme '{scheme}'.")
        self._hasher = PasswordHasher()

    def hash_password(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False


class TokenService:
    def __init__(self, settings: AuthRuntimeSettings) -> None:
        self.settings = settings

    def create_access_token(self, user: User) -> tuple[str, int]:
        issued_at = datetime.now(timezone.utc)
        expires_at = issued_at + self.settings.access_token_ttl
        token = jwt.encode(
            {
                "sub": user.id,
                "username": user.username,
                "role": user.role.value,
                "jti": secrets.token_hex(8),
                "type": "access",
                "iat": int(issued_at.timestamp()),
                "exp": int(expires_at.timestamp()),
            },
            self.settings.secret_key,
            algorithm=self.settings.algorithm,
        )
        return token, int(self.settings.access_token_ttl.total_seconds())

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self.settings.secret_key,
                algorithms=[self.settings.algorithm],
            )
        except jwt.PyJWTError as error:
            raise InvalidTokenError("The access token is invalid or expired.") from error

        if payload.get("type") != "access":
            raise InvalidTokenError("The token is not an access token.")

        exp = payload.get("exp")
        if not isinstance(exp, int):
            raise InvalidTokenError("The token expiry is invalid.")

        return AccessTokenClaims(
            user_id=str(payload["sub"]),
            username=str(payload["username"]),
            role=str(payload["role"]),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
        )

    def generate_refresh_token(self) -> tuple[str, int]:
        return secrets.token_urlsafe(48), int(self.settings.refresh_token_ttl.total_seconds())

    def hash_refresh_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

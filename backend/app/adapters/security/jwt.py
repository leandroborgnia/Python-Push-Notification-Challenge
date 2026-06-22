from __future__ import annotations

from datetime import timedelta

import jwt

from app.domain.errors import TokenError
from app.ports.clock import Clock


class PyJwtTokenService:
    """`TokenService` port impl using PyJWT (HS256). Constitution VI forbids python-jose."""

    def __init__(self, *, secret: str, algorithm: str, access_ttl_min: int, clock: Clock) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._ttl = timedelta(minutes=access_ttl_min)
        self._clock = clock

    def issue_access_token(self, subject: str) -> str:
        now = self._clock.now()
        payload = {
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int((now + self._ttl).timestamp()),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_subject(self, token: str) -> str:
        # Verify the signature with PyJWT, but check expiry against the injected clock so token
        # validity is consistent with the rest of the app (and deterministic under a fixed clock).
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                # Signature is verified; the time-based claims are checked against the injected
                # clock below, not PyJWT's real wall-clock.
                options={"verify_exp": False, "verify_iat": False, "verify_nbf": False},
            )
        except jwt.PyJWTError as exc:
            raise TokenError("invalid access token") from exc
        exp = payload.get("exp")
        if not isinstance(exp, int | float) or self._clock.now().timestamp() >= exp:
            raise TokenError("expired access token")
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject:
            raise TokenError("token missing subject")
        return subject

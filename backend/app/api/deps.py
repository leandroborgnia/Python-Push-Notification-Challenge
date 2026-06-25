from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.bootstrap import Container
from app.domain.errors import TokenError

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login", auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def current_user(
    container: ContainerDep,
    token: Annotated[str | None, Depends(_oauth2_scheme)],
) -> UUID:
    """Resolve the caller's user id from a Bearer access token.

    Returns 401 on a missing, malformed, signature-invalid, or expired token (FR-006).
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    try:
        return UUID(container.token_service.decode_subject(token))
    except (TokenError, ValueError) as exc:
        raise credentials_error from exc


CurrentUser = Annotated[UUID, Depends(current_user)]


async def current_admin(container: ContainerDep, user_id: CurrentUser) -> UUID:
    """Resolve the caller and require admin privileges.

    Layers on ``current_user`` (401 for a missing/invalid/expired token, unchanged) and raises 403
    for an authenticated non-admin (FR-005). Returns the admin's user id.
    """
    if not await container.accounts.is_admin(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin privileges required"
        )
    return user_id


CurrentAdmin = Annotated[UUID, Depends(current_admin)]

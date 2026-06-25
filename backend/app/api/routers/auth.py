from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Response, status

from app.api.deps import ContainerDep, CurrentUser
from app.api.schemas import RegisterRequest, ResetConfirm, ResetRequest, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me")
async def me(user_id: CurrentUser) -> dict[str, str]:
    """Return the authenticated caller's id — a minimal token-gated endpoint (FR-006)."""
    return {"user_id": str(user_id)}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, container: ContainerDep) -> dict[str, str]:
    """Create an unverified account and email a verification token (FR-001/FR-003)."""
    await container.accounts.register(str(body.email), body.password)
    return {"status": "registered"}


@router.post("/verify")
async def verify(token: str, container: ContainerDep) -> dict[str, str]:
    """Consume a single-use verification token (FR-003)."""
    await container.accounts.verify_email(token)
    return {"status": "verified"}


@router.post("/login", response_model=TokenResponse)
async def login(
    container: ContainerDep,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> TokenResponse:
    """OAuth2 password login → access token; verified accounts only (FR-004)."""
    access_token = await container.accounts.login(username, password)
    return TokenResponse(access_token=access_token)


@router.post("/reset-request", status_code=status.HTTP_202_ACCEPTED)
async def reset_request(body: ResetRequest, container: ContainerDep) -> Response:
    """Request a password-reset email. Always 202 (no account enumeration), FR-005."""
    await container.accounts.request_reset(str(body.email))
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/reset-confirm")
async def reset_confirm(body: ResetConfirm, container: ContainerDep) -> dict[str, str]:
    """Set a new password via a reset token; the old password stops working (FR-005)."""
    await container.accounts.reset_password(body.token, body.new_password)
    return {"status": "password updated"}

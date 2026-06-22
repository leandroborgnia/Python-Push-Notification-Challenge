from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.channels import Channel
from app.domain.health import HealthStatus, ReadinessReport

# --- Auth (US1) -----------------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ResetRequest(BaseModel):
    email: EmailStr


class ResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


# --- Contacts (US4) -------------------------------------------------------------------------------


class ContactCreate(BaseModel):
    display_name: str
    email: EmailStr | None = None
    phone: str | None = None
    device_token: str | None = None


class ContactOut(BaseModel):
    id: UUID
    display_name: str
    email: str | None = None
    phone: str | None = None
    device_token: str | None = None


# --- Templates (US2) ------------------------------------------------------------------------------


class TemplateCreate(BaseModel):
    title: str
    content: str
    channel: Channel
    recipient_contact_ids: list[UUID]


class TemplateOut(BaseModel):
    id: UUID
    title: str
    content: str
    channel: Channel
    recipient_contact_ids: list[UUID]


# --- Sends, status & webhooks (US3) ---------------------------------------------------------------


class DispatchAck(BaseModel):
    dispatch_id: UUID
    status: str = "accepted"


class TransitionOut(BaseModel):
    from_status: str | None = None
    to_status: str
    reason: str | None = None
    attempt: int | None = None
    at: datetime | None = None


class DeliveryStatusOut(BaseModel):
    delivery_id: UUID
    recipient_name: str
    destination: str | None = None
    status: str
    failure_reason: str | None = None
    transitions: list[TransitionOut]


class DispatchStatusOut(BaseModel):
    dispatch_id: UUID
    channel: Channel
    created_at: datetime | None = None
    deliveries: list[DeliveryStatusOut]


class WebhookConfirmation(BaseModel):
    provider_ref: str
    outcome: Literal["delivered", "failed"]
    reason: str | None = None


class LiveResponse(BaseModel):
    status: str = "alive"


class ReadyResponse(BaseModel):
    status: str
    detail: str | None = None


class SubsystemCheckOut(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class ReadinessReportOut(BaseModel):
    status: HealthStatus
    checked_at: datetime
    checks: list[SubsystemCheckOut]

    @classmethod
    def from_domain(cls, report: ReadinessReport) -> ReadinessReportOut:
        return cls(
            status=report.status,
            checked_at=report.checked_at,
            checks=[
                SubsystemCheckOut(name=check.name.value, passed=check.passed, detail=check.detail)
                for check in report.checks
            ],
        )

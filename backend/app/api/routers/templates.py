from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.deps import ContainerDep, CurrentUser
from app.api.schemas import TemplateCreate, TemplateOut
from app.domain.templates import Template

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


def _to_out(template: Template) -> TemplateOut:
    return TemplateOut(
        id=template.id,
        title=template.title,
        content=template.content,
        channel=template.channel,
        recipient_contact_ids=list(template.recipient_ids),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TemplateOut)
async def create_template(
    body: TemplateCreate, container: ContainerDep, user_id: CurrentUser
) -> TemplateOut:
    """Create a template; never sends (FR-011/FR-017). 422 on SMS>160 / foreign recipient."""
    template = await container.templates.create(
        user_id,
        title=body.title,
        content=body.content,
        channel=body.channel.value,
        recipient_ids=body.recipient_contact_ids,
    )
    return _to_out(template)


@router.get("", response_model=list[TemplateOut])
async def list_templates(
    container: ContainerDep,
    user_id: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TemplateOut]:
    """List only the caller's own templates (FR-014)."""
    templates = await container.templates.list(user_id, limit=limit, offset=offset)
    return [_to_out(template) for template in templates]


@router.put("/{template_id}", response_model=TemplateOut)
async def modify_template(
    template_id: UUID, body: TemplateCreate, container: ContainerDep, user_id: CurrentUser
) -> TemplateOut:
    """Modify an owned template; never sends (FR-012/FR-017). 404 if not owned."""
    template = await container.templates.modify(
        user_id,
        template_id,
        title=body.title,
        content=body.content,
        channel=body.channel.value,
        recipient_ids=body.recipient_contact_ids,
    )
    return _to_out(template)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID, container: ContainerDep, user_id: CurrentUser
) -> Response:
    """Delete an owned template (FR-013). 404 if not owned."""
    await container.templates.delete(user_id, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

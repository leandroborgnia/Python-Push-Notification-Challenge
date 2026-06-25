from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.settings import _PLACEHOLDER_ADMIN_PASSWORD, _PLACEHOLDER_JWT_SECRET, Settings

_REAL_JWT = "a-real-production-jwt-secret-value-32b!"
_REAL_ADMIN_PW = "a-real-production-admin-password"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "jwt_secret": _REAL_JWT,
        "admin_password": _REAL_ADMIN_PW,
    }
    base.update(overrides)
    # Explicit init kwargs take precedence over env / .env in pydantic-settings, so these tests are
    # insulated from a developer's local environment.
    return Settings(**base)  # type: ignore[arg-type]


def test_admin_password_placeholder_accepted_in_dev() -> None:
    settings = _settings(environment="dev", admin_password=_PLACEHOLDER_ADMIN_PASSWORD)
    assert settings.admin_password == _PLACEHOLDER_ADMIN_PASSWORD


def test_admin_password_placeholder_refused_outside_dev() -> None:
    with pytest.raises(PydanticValidationError, match="ADMIN_PASSWORD"):
        _settings(environment="prod", admin_password=_PLACEHOLDER_ADMIN_PASSWORD)


def test_real_admin_password_accepted_outside_dev() -> None:
    settings = _settings(environment="prod", admin_password=_REAL_ADMIN_PW)
    assert settings.admin_password == _REAL_ADMIN_PW


def test_jwt_placeholder_refused_outside_dev() -> None:
    with pytest.raises(PydanticValidationError, match="JWT_SECRET"):
        _settings(environment="prod", jwt_secret=_PLACEHOLDER_JWT_SECRET)

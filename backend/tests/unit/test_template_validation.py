from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.channels import Channel
from app.domain.errors import ValidationError
from app.domain.templates import (
    SMS_MAX_LENGTH,
    ensure_recipients_owned,
    parse_channel,
    validate_sms_length,
)


def test_parse_channel_accepts_known_values() -> None:
    assert parse_channel("email") is Channel.EMAIL
    assert parse_channel("sms") is Channel.SMS
    assert parse_channel("push") is Channel.PUSH


def test_parse_channel_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        parse_channel("telegram")


def test_sms_length_ok_at_limit() -> None:
    validate_sms_length(Channel.SMS, "x" * SMS_MAX_LENGTH)  # exactly 160 → no raise


def test_sms_length_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_sms_length(Channel.SMS, "x" * (SMS_MAX_LENGTH + 1))


def test_sms_length_not_enforced_for_other_channels() -> None:
    validate_sms_length(Channel.EMAIL, "x" * (SMS_MAX_LENGTH * 10))  # no raise


def test_recipients_owned_accepts_subset() -> None:
    a, b = uuid4(), uuid4()
    ensure_recipients_owned([a, b], {a, b})


def test_recipients_owned_rejects_foreign_contact() -> None:
    owned, foreign = uuid4(), uuid4()
    with pytest.raises(ValidationError):
        ensure_recipients_owned([owned, foreign], {owned})

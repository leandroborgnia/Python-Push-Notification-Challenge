from __future__ import annotations

import pytest

from app.domain.dispatch import DeliveryStatus, is_terminal, validate_transition
from app.domain.errors import ValidationError

S = DeliveryStatus


def test_allowed_transitions() -> None:
    validate_transition(S.QUEUED, S.SENT)
    validate_transition(S.QUEUED, S.FAILED)  # direct pre-send-validation failure (FR-022)
    validate_transition(S.SENT, S.DELIVERED)
    validate_transition(S.SENT, S.FAILED)


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (S.QUEUED, S.DELIVERED),  # must pass through 'sent'
        (S.SENT, S.QUEUED),  # no going back
        (S.DELIVERED, S.SENT),  # terminal — never overwritten
        (S.DELIVERED, S.FAILED),
        (S.FAILED, S.DELIVERED),
        (S.SENT, S.SENT),
    ],
)
def test_illegal_transitions_rejected(frm: DeliveryStatus, to: DeliveryStatus) -> None:
    with pytest.raises(ValidationError):
        validate_transition(frm, to)


def test_terminal_states() -> None:
    assert is_terminal(S.DELIVERED) is True
    assert is_terminal(S.FAILED) is True
    assert is_terminal(S.QUEUED) is False
    assert is_terminal(S.SENT) is False

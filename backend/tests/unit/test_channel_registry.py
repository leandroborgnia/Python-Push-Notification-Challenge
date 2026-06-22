"""Open/Closed guard (constitution II, FR-028 / SC-008).

Two properties keep "add a channel = one new adapter + one bootstrap line, touch nothing else" true:
1. the registry resolves *every* ``Channel`` to an adapter that satisfies ``ChannelPort``;
2. the shared dispatch/resilience core (``application/sending`` + ``application/delivery``) imports
   no concrete channel adapter — it depends only on the ``ChannelPort`` seam.
"""

from __future__ import annotations

import ast
import importlib

import pytest

from app.bootstrap import build_channel_registry
from app.domain.channels import Channel
from app.settings import get_settings

# The dispatch core: code that fans out / delivers across channels. It must stay channel-agnostic.
_DISPATCH_CORE_MODULES = ("app.application.sending", "app.application.delivery")
_CONCRETE_ADAPTER_PKG = "app.adapters.channels"


def test_registry_resolves_every_channel() -> None:
    registry = build_channel_registry(get_settings())

    # Every enum member is bound, and each adapter reports the channel it was registered under.
    assert set(registry) == set(Channel)
    for channel, adapter in registry.items():
        assert adapter.channel is channel
        # Duck-typed ChannelPort surface (the strategy seam every channel implements).
        for method in ("destination_of", "validate", "send", "confirmation_mode", "poll_status"):
            assert callable(getattr(adapter, method))


@pytest.mark.parametrize("module_name", _DISPATCH_CORE_MODULES)
def test_dispatch_core_imports_no_concrete_channel(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__file__ is not None
    with open(module.__file__, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=module.__file__)

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offenders = [name for name in imported if name.startswith(_CONCRETE_ADAPTER_PKG)]
    assert offenders == [], (
        f"{module_name} must depend only on the ChannelPort seam, "
        f"not concrete channel adapters: {offenders}"
    )

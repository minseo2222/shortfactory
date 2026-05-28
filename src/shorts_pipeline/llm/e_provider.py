"""Provider protocol for E script/title generation.

No real provider adapters live here. Phase 5 accepts only caller-injected
mock/fake providers that implement this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol


class EScriptProvider(Protocol):
    provider_name: str
    model_name: str

    def generate(
        self,
        *,
        context: dict[str, Any],
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        """Return a raw E script/title payload for validation by the service."""

"""Provider protocol for B scene-plan generation.

No real provider adapters live here. Phase 2 accepts only caller-injected
mock/fake providers that implement this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol

from shorts_pipeline.models import SourceArtifact


class BScenePlanProvider(Protocol):
    provider_name: str
    model_name: str

    def generate(
        self,
        *,
        source: SourceArtifact,
        prompt_version: str,
        previous_errors: list[str],
    ) -> dict[str, Any]:
        """Return a raw B scene-plan payload for validation by the service."""

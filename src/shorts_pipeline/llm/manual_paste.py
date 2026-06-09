"""No-API "manual paste" bridge for B/E generation.

Lets a user generate the LLM-shaped artifacts with their own Claude Code / Codex
CLI instead of a paid API key: the tool exports a self-contained prompt
(``build_*_paste_prompt``), the user runs it in their CLI, and the returned JSON
is fed back through the SAME provider seam + validators as a real provider
(``ManualPaste*Provider``). No network, no SDK, no key.

The exported prompt reuses the real provider's system prompt (which already
embeds the exact JSON schema + safety rules) and the outbound minimization, so
only the bounded, allow-listed source fields leave the machine - never URLs,
paths, hashes, or secrets.
"""

from __future__ import annotations

from typing import Any

from shorts_pipeline.llm.real_providers import (
    _b_system_prompt,
    _e_system_prompt,
    _parse_json_object,
    _user_prompt,
    minimize_b_source,
    minimize_e_context,
)
from shorts_pipeline.models import SourceArtifact

_KOREAN_OUTPUT_RULE = (
    "모든 화면 문구(screen_text)·내레이션·제목은 한국어로 작성하세요. "
    "위 스키마를 정확히 따르는 JSON 객체 하나만 출력하세요. 설명·코드펜스 금지."
)


class ManualPasteBScenePlanProvider:
    """B provider that returns a user-pasted payload for the service to validate."""

    provider_name = "manual-paste"
    model_name = "claude-code-or-codex"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def generate(
        self, *, source: SourceArtifact, prompt_version: str, previous_errors: list[str]
    ) -> dict[str, Any]:
        return self._payload


class ManualPasteEScriptProvider:
    """E provider that returns a user-pasted payload for the service to validate."""

    provider_name = "manual-paste"
    model_name = "claude-code-or-codex"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def generate(
        self, *, context: dict[str, Any], prompt_version: str, previous_errors: list[str]
    ) -> dict[str, Any]:
        return self._payload


def build_b_paste_prompt(
    source: SourceArtifact, previous_errors: list[str] | None = None
) -> str:
    """Self-contained B prompt to paste into Claude Code / Codex."""
    minimal = minimize_b_source(source.model_dump(mode="json"))
    user = _user_prompt(minimal, previous_errors or [])
    return f"{_b_system_prompt()}\n\n{user}\n\n{_KOREAN_OUTPUT_RULE}"


def build_e_paste_prompt(
    context: dict[str, Any], previous_errors: list[str] | None = None
) -> str:
    """Self-contained E prompt to paste into Claude Code / Codex."""
    minimal = minimize_e_context(context)
    user = _user_prompt(minimal, previous_errors or [])
    return f"{_e_system_prompt()}\n\n{user}\n\n{_KOREAN_OUTPUT_RULE}"


def parse_pasted_json(raw: str) -> dict[str, Any]:
    """Tolerantly parse pasted model output into a single JSON object.

    Accepts code-fenced or prose-wrapped JSON (same tolerance as the real
    providers). Raises ValueError with a clear Korean message on failure.
    """
    if not (raw or "").strip():
        raise ValueError("붙여넣은 내용이 비어 있습니다.")
    try:
        return _parse_json_object(raw)
    except Exception as exc:  # normalize to a friendly message
        raise ValueError(f"붙여넣은 내용에서 JSON 객체를 읽지 못했습니다: {exc}") from exc

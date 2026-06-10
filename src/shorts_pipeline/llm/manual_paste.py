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
from shorts_pipeline.llm.tone_variants import VARIANT_TONE_PRESETS
from shorts_pipeline.models import SourceArtifact

_KOREAN_OUTPUT_RULE = (
    "모든 화면 문구(screen_text)·내레이션·제목은 한국어로 작성하세요. "
    "위 스키마를 정확히 따르는 JSON 객체 하나만 출력하세요. 설명·코드펜스 금지."
)

DEFAULT_TONE = "자극적"
TONE_PRESETS: dict[str, str] = {
    "자극적": (
        "톤=자극적: 가장 센 훅·궁금증·감정으로 끝까지 보게 만든다. "
        "단 사실 기반으로만, 과장·날조·비방 금지."
    ),
    "커뮤니티(반말·밈)": (
        "톤=커뮤니티(반말·밈): 한국 인터넷 커뮤니티 말투로 써라. 반말·빠른 호흡, "
        "밈 어미·드립(ㅋㅋ, ㄹㅇ, 팩트, ~노, ~임, 실화냐, 인정?)으로 후킹을 세게. "
        "단 욕설·비속어·혐오·인신공격·특정인 비하·신상·날조는 절대 금지(사실 기반 자극만)."
    ),
    "정보": (
        "톤=정보전달: 핵심 가치를 빠르게 압축하고 '이거 모르면 손해' 식 실용 훅을 쓴다. "
        "정확하고 간결하게."
    ),
    "유머": (
        "톤=유머: 위트·밈 감성·반전 개그로 가볍고 빠른 호흡. 조롱·비방은 금지."
    ),
    "감성": (
        "톤=감성: 공감과 여운이 있는 스토리텔링, 따뜻한 한 줄로 마무리."
    ),
}

# Researched variant presets (humor/issue/감성 structures) merged in. The five
# base tones above stay first so 자극적 remains the default.
for _name, _instruction in VARIANT_TONE_PRESETS.items():
    TONE_PRESETS.setdefault(_name, _instruction)


def tone_block(tone: str | None) -> str:
    return TONE_PRESETS.get((tone or "").strip() or DEFAULT_TONE, TONE_PRESETS[DEFAULT_TONE])


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
    source: SourceArtifact,
    previous_errors: list[str] | None = None,
    tone: str = DEFAULT_TONE,
) -> str:
    """Self-contained B prompt to paste into Claude Code / Codex."""
    minimal = minimize_b_source(source.model_dump(mode="json"))
    user = _user_prompt(minimal, previous_errors or [])
    return f"{_b_system_prompt()}\n{tone_block(tone)}\n\n{user}\n\n{_KOREAN_OUTPUT_RULE}"


def build_e_paste_prompt(
    context: dict[str, Any],
    previous_errors: list[str] | None = None,
    tone: str = DEFAULT_TONE,
) -> str:
    """Self-contained E prompt to paste into Claude Code / Codex."""
    minimal = minimize_e_context(context)
    user = _user_prompt(minimal, previous_errors or [])
    return f"{_e_system_prompt()}\n{tone_block(tone)}\n\n{user}\n\n{_KOREAN_OUTPUT_RULE}"


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

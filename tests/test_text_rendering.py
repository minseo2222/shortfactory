"""Tests that generated PNGs render Korean (CJK) text rather than destroying it.

The previous implementation passed text through a latin-1 round-trip, which
turned Hangul into ``?`` before drawing. These tests lock in the fix: the
round-trip is gone, and when a CJK-capable font is available the Korean text
actually renders glyph pixels. The glyph-pixel assertions are skipped when no
CJK font is installed (e.g. minimal CI), but the regression guards always run.
"""

from __future__ import annotations

import pytest
from PIL import Image

from shorts_pipeline.projectgen import placeholder, text_overlay
from shorts_pipeline.projectgen.fonts import has_cjk_font

KOREAN = "실명 공개 무조건 논란 정리"


def test_latin1_round_trip_is_removed() -> None:
    # The destructive helper must no longer exist in either module.
    assert not hasattr(text_overlay, "_safe_text")
    assert not hasattr(placeholder, "_safe_text")


def _light_glyph_pixels(image: Image.Image) -> int:
    rgb = image.convert("RGB")
    return sum(1 for r, g, b in rgb.getdata() if r > 200 and g > 200 and b > 200)


def test_text_overlay_renders_korean_glyphs(tmp_path) -> None:
    if not has_cjk_font():
        pytest.skip("no CJK font installed; Hangul glyph rendering cannot be verified")
    path = text_overlay.create_text_overlay_png(KOREAN, tmp_path / "s01_text.png")
    assert path.is_file()
    image = Image.open(path)
    # White text fill over a semi-transparent box: a meaningful number of bright
    # pixels means the Hangul actually rendered (not blanked or turned into '?').
    assert _light_glyph_pixels(image) > 500


def test_placeholder_renders_korean_glyphs(tmp_path) -> None:
    if not has_cjk_font():
        pytest.skip("no CJK font installed; Hangul glyph rendering cannot be verified")
    path = placeholder.create_placeholder_png(
        "slot_001",
        tmp_path / "slot_001.png",
        scene_id="s01",
        image_slot_description="중립적이고 안전한 한국어 설명 이미지",
        avoid_claims=["허위 수치 추가 금지", "실명 공개 금지"],
    )
    assert path.is_file()
    assert _light_glyph_pixels(Image.open(path)) > 500


def test_overlay_handles_empty_text(tmp_path) -> None:
    # Empty/whitespace-only text must still produce a valid PNG (no crash).
    path = text_overlay.create_text_overlay_png("", tmp_path / "empty.png")
    assert path.is_file()
    assert Image.open(path).size[0] > 0

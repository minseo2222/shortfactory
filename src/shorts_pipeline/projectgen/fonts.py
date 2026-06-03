"""CJK-capable font resolution for generated PNG assets.

The pipeline targets Korean community content, so the generated text-overlay and
placeholder PNGs must render Hangul. PIL's built-in bitmap font has no CJK
glyphs, so this module locates a TrueType/OpenType CJK font from common
platform locations (overridable via ``SHORTS_PIPELINE_FONT_PATH``) and falls
back to PIL's default font only when none is found.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONT_PATH_ENV = "SHORTS_PIPELINE_FONT_PATH"

# Common CJK-capable fonts across platforms, in preference order.
_CJK_FONT_CANDIDATES: tuple[str, ...] = (
    # Windows (Malgun Gothic ships with Korean Windows)
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "C:/Windows/Fonts/gulim.ttc",
    "C:/Windows/Fonts/batang.ttc",
    # Linux (Noto / Nanum)
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    # macOS
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/AppleGothic.ttf",
)


@lru_cache(maxsize=1)
def find_cjk_font_path() -> str | None:
    """Return the first available CJK font path, or None if none is found."""
    override = os.environ.get(FONT_PATH_ENV, "").strip()
    candidates = (override, *_CJK_FONT_CANDIDATES) if override else _CJK_FONT_CANDIDATES
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def has_cjk_font() -> bool:
    """True when a CJK-capable TrueType font is available on this machine."""
    return find_cjk_font_path() is not None


def load_font(size: int) -> ImageFont.ImageFont:
    """Load a CJK-capable font at ``size``, or PIL's default if none is found.

    The default font cannot render Hangul, but it is only reached when no CJK
    font is installed; user-facing renders on a configured machine use the
    resolved TrueType font.
    """
    path = find_cjk_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()

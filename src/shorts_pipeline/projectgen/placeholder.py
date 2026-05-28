"""Placeholder image generation interface."""

from __future__ import annotations

from pathlib import Path
import textwrap

from PIL import Image, ImageDraw

from shorts_pipeline.models import CanvasSpec
from shorts_pipeline.security import validate_media_extension

PLACEHOLDER_BACKGROUND = "#1f2937"
PLACEHOLDER_TEXT = "#f8fafc"
PLACEHOLDER_MUTED_TEXT = "#cbd5e1"
PLACEHOLDER_WARNINGS = (
    "Avoid: real names, nicknames, faces without rights/consent,",
    "personal information, original post/comment screenshots,",
    "copyrighted images without rights, risky community logos.",
)


def _safe_text(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _validate_output_path(output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".png":
        validate_media_extension(path)
    if not path.is_absolute():
        validate_media_extension(path)
    return path


def create_placeholder_png(
    slot_id: str,
    output_path: str | Path,
    canvas: CanvasSpec | None = None,
    *,
    scene_id: str = "",
    image_slot_description: str = "",
    avoid_claims: list[str] | None = None,
) -> Path:
    """Create a simple local placeholder PNG for a user-replaceable image slot."""
    path = _validate_output_path(output_path)
    canvas = canvas or CanvasSpec()
    path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (canvas.width, canvas.height), PLACEHOLDER_BACKGROUND)
    draw = ImageDraw.Draw(image)
    slot_label = slot_id.upper()
    if scene_id:
        slot_label = f"{slot_label} / SCENE {scene_id}"

    description = image_slot_description or "User-selected safe supporting image"
    lines = [
        slot_label,
        "",
        "Needed image:",
        *textwrap.wrap(description, width=34),
        "",
        *PLACEHOLDER_WARNINGS,
    ]
    if avoid_claims:
        lines.extend(["", "Avoid claims:"])
        for claim in avoid_claims[:4]:
            lines.extend(textwrap.wrap(f"- {claim}", width=42))

    y = 180
    for index, line in enumerate(lines):
        fill = PLACEHOLDER_TEXT if index == 0 else PLACEHOLDER_MUTED_TEXT
        draw.text((90, y), _safe_text(line), fill=fill)
        y += 44

    image.save(path)
    return path

"""Text overlay PNG generation interface."""

from __future__ import annotations

from pathlib import Path
import textwrap

from PIL import Image, ImageDraw

from shorts_pipeline.models import CanvasSpec
from shorts_pipeline.security import validate_media_extension


def _safe_text(text: str) -> str:
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _validate_output_path(output_path: str | Path) -> Path:
    path = Path(output_path)
    if path.suffix.lower() != ".png":
        validate_media_extension(path)
    if not path.is_absolute():
        validate_media_extension(path)
    return path


def create_text_overlay_png(
    text: str,
    output_path: str | Path,
    canvas: CanvasSpec | None = None,
) -> Path:
    """Create a transparent PNG containing simple scene screen text."""
    path = _validate_output_path(output_path)
    canvas = canvas or CanvasSpec()
    path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGBA", (canvas.width, canvas.height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    box_top = int(canvas.height * 0.18)
    box_bottom = box_top + 220
    draw.rectangle((80, box_top, canvas.width - 80, box_bottom), fill=(0, 0, 0, 176))
    wrapped = "\n".join(textwrap.wrap(_safe_text(text), width=18))
    draw.multiline_text(
        (canvas.width // 2, box_top + 110),
        wrapped,
        fill=(255, 255, 255, 255),
        anchor="mm",
        align="center",
        spacing=12,
    )
    image.save(path)
    return path

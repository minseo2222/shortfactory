"""Generate local image replacement instructions for C outputs."""

from __future__ import annotations

from shorts_pipeline.models import TimelineJson


def build_replace_images_markdown(project_id: str, timeline: TimelineJson) -> str:
    """Build the concise local guide for manual image replacement."""
    lines = [
        "# Replace Images",
        "",
        f"Project: `{project_id}`",
        "",
        "Replace the user image slot files under `assets/user_images/`.",
        "Backup placeholders live under `assets/placeholders/` and should not be edited "
        "unless you intentionally want to change the fallback images.",
        "",
        "Do not use original post screenshots, comment screenshots, personal information, "
        "real names or nicknames, faces without rights/consent, copyrighted images without "
        "rights, or risky community logos.",
        "",
        "Phase D will later collect rights confirmation in `d_image_manifest.json`.",
        "",
        "| scene | slot | file | needed image | avoid |",
        "|---|---|---|---|---|",
    ]
    for scene in timeline.scenes:
        avoid = "; ".join(scene.avoid_claims) if scene.avoid_claims else "unsafe claims or identities"
        lines.append(
            "| "
            f"{scene.scene_id} | "
            f"{scene.image_slot_id} | "
            f"`{scene.image_path}` | "
            f"{scene.image_slot_description} | "
            f"{avoid} |"
        )
    lines.append("")
    return "\n".join(lines)

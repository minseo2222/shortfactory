"""File, resource, and XML safety helpers."""

from __future__ import annotations

import hashlib
from html import escape
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class SecurityValidationError(ValueError):
    """Raised when a path or resource violates local project safety rules."""


def ensure_relative_project_path(path: str | Path) -> Path:
    """Validate that a path is relative and stays inside a project directory."""
    raw = str(path)
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        raise SecurityValidationError("external resource URLs are not allowed")

    candidate = Path(path)
    if candidate.is_absolute() or candidate.anchor:
        raise SecurityValidationError("absolute paths are not allowed")
    if any(part == ".." for part in candidate.parts):
        raise SecurityValidationError("path traversal is not allowed")
    if not raw.strip():
        raise SecurityValidationError("path must not be empty")
    return candidate


def ensure_path_under_root(root: str | Path, path: str | Path) -> Path:
    """Resolve a path and ensure it is inside the given root directory."""
    root_path = Path(root).resolve()
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(root_path)
    except ValueError as exc:
        raise SecurityValidationError("path escapes configured project root") from exc
    return candidate


def reject_external_resource(resource: str) -> None:
    """Reject URL-like external resources."""
    parsed = urlparse(resource)
    if parsed.scheme or parsed.netloc:
        raise SecurityValidationError("external resources are not allowed")


def xml_escape_text(text: str) -> str:
    """Escape text before inserting it into XML content or attributes."""
    return escape(text, quote=True)


def validate_media_extension(path: str | Path) -> None:
    """Ensure a media path is project-relative and has an allowed extension."""
    candidate = ensure_relative_project_path(path)
    if candidate.suffix.lower() not in ALLOWED_MEDIA_EXTENSIONS:
        raise SecurityValidationError(f"unsupported media extension: {candidate.suffix}")


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest for a local file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

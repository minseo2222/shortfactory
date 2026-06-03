"""File, resource, and XML safety helpers."""

from __future__ import annotations

import hashlib
import re
from html import escape
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

ALLOWED_MEDIA_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


class SecurityValidationError(ValueError):
    """Raised when a path or resource violates local project safety rules."""


def ensure_relative_project_path(path: str | Path) -> Path:
    """Validate that a path is relative and stays inside a project directory.

    The check is platform-independent: backslashes are normalized to forward
    slashes and the path is analyzed with POSIX semantics, so Windows-style
    traversal (``foo\\..\\bar``), drive-relative paths (``C:foo``), and UNC
    paths (``\\\\server\\share``) are rejected identically on Linux and Windows.
    """
    raw = str(path)
    if not raw.strip():
        raise SecurityValidationError("path must not be empty")

    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        raise SecurityValidationError("external resource URLs are not allowed")

    normalized = raw.replace("\\", "/")
    if _DRIVE_PREFIX.match(normalized):
        raise SecurityValidationError("drive-letter paths are not allowed")
    if normalized.startswith("/"):
        raise SecurityValidationError("absolute paths are not allowed")

    posix = PurePosixPath(normalized)
    if posix.is_absolute() or posix.anchor:
        raise SecurityValidationError("absolute paths are not allowed")
    if any(part == ".." for part in posix.parts):
        raise SecurityValidationError("path traversal is not allowed")
    return Path(normalized)


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

from __future__ import annotations

import pytest

from shorts_pipeline.security import (
    SecurityValidationError,
    ensure_relative_project_path,
    reject_external_resource,
    validate_media_extension,
)


def test_path_traversal_rejected() -> None:
    with pytest.raises(SecurityValidationError):
        ensure_relative_project_path("../evil.png")


def test_absolute_path_rejected() -> None:
    with pytest.raises(SecurityValidationError):
        ensure_relative_project_path("/absolute/path.png")


def test_external_url_resource_rejected() -> None:
    with pytest.raises(SecurityValidationError):
        reject_external_resource("https://example.com/a.png")
    with pytest.raises(SecurityValidationError):
        validate_media_extension("https://example.com/a.png")


def test_valid_relative_media_path_passes() -> None:
    validate_media_extension("assets/user_images/slot_001.png")
    assert ensure_relative_project_path("assets/user_images/slot_001.png").as_posix().endswith(
        "slot_001.png"
    )


def test_invalid_media_extension_rejected() -> None:
    with pytest.raises(SecurityValidationError):
        validate_media_extension("assets/user_images/slot_001.exe")


@pytest.mark.parametrize(
    "unsafe",
    [
        "C:foo/bar.png",          # drive-relative
        "C:/abs/bar.png",         # drive-absolute
        "foo\\..\\bar.png",       # backslash traversal (invisible to a POSIX Path)
        "\\\\server\\share\\x",   # UNC
        "/abs/x.png",             # POSIX absolute
        "a/../b.png",             # embedded traversal
        "  ",                     # blank
    ],
)
def test_platform_independent_unsafe_paths_rejected(unsafe: str) -> None:
    # These must be rejected identically on Windows and Linux: the guard
    # normalizes backslashes and analyses with POSIX semantics.
    with pytest.raises(SecurityValidationError):
        ensure_relative_project_path(unsafe)


def test_backslash_separated_safe_path_is_normalized() -> None:
    # A safe relative path that happens to use backslash separators (e.g. a
    # Windows Path stringified) is normalized to forward slashes, not rejected.
    result = ensure_relative_project_path("assets\\user_images\\slot_001.png")
    assert result.as_posix() == "assets/user_images/slot_001.png"

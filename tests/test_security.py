from __future__ import annotations

import pytest

from shorts_pipeline.security import (
    SecurityValidationError,
    ensure_relative_project_path,
    reject_external_resource,
    validate_media_extension,
    xml_escape_text,
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


def test_xml_escape_helper_escapes_special_chars() -> None:
    escaped = xml_escape_text("<tag attr=\"value\">A&B's</tag>")
    assert "&lt;tag" in escaped
    assert "&quot;value&quot;" in escaped
    assert "A&amp;B" in escaped
    assert "&gt;" in escaped

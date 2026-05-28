from __future__ import annotations

from pathlib import Path


BIDI_CONTROL_CHARS = {
    "\u202A": "LEFT-TO-RIGHT EMBEDDING",
    "\u202B": "RIGHT-TO-LEFT EMBEDDING",
    "\u202C": "POP DIRECTIONAL FORMATTING",
    "\u202D": "LEFT-TO-RIGHT OVERRIDE",
    "\u202E": "RIGHT-TO-LEFT OVERRIDE",
    "\u2066": "LEFT-TO-RIGHT ISOLATE",
    "\u2067": "RIGHT-TO-LEFT ISOLATE",
    "\u2068": "FIRST STRONG ISOLATE",
    "\u2069": "POP DIRECTIONAL ISOLATE",
    "\u200B": "ZERO WIDTH SPACE",
    "\u200C": "ZERO WIDTH NON-JOINER",
    "\u200D": "ZERO WIDTH JOINER",
    "\uFEFF": "BOM / ZERO WIDTH NO-BREAK SPACE",
}


def _selected_text_paths() -> list[Path]:
    explicit_paths = [
        Path(".gitattributes"),
        Path("README.md"),
        Path("AGENTS.md"),
        Path("pyproject.toml"),
        Path(".github/workflows/ci.yml"),
    ]
    discovered_paths = [
        *Path("docs").rglob("*.md"),
        *Path("src").rglob("*.py"),
        *Path("tests").rglob("*.py"),
        *Path("schemas").rglob("*.md"),
    ]
    return sorted({path for path in [*explicit_paths, *discovered_paths] if path.is_file()})


def test_selected_text_files_use_lf_line_endings() -> None:
    failures: list[str] = []

    for path in _selected_text_paths():
        data = path.read_bytes()
        if b"\r\n" in data:
            failures.append(f"{path.as_posix()}: contains CRLF line endings")
        elif b"\r" in data:
            failures.append(f"{path.as_posix()}: contains CR-only line endings")

    assert not failures, "\n".join(failures)


def test_selected_text_files_do_not_contain_hidden_unicode_controls() -> None:
    failures: list[str] = []

    for path in _selected_text_paths():
        text = path.read_text(encoding="utf-8")
        for index, char in enumerate(text):
            if char not in BIDI_CONTROL_CHARS:
                continue
            line_no = text.count("\n", 0, index) + 1
            line_start = text.rfind("\n", 0, index) + 1
            column_no = index - line_start + 1
            failures.append(
                f"{path.as_posix()}:{line_no}:{column_no}: "
                f"U+{ord(char):04X} {BIDI_CONTROL_CHARS[char]}"
            )

    assert not failures, "\n".join(failures)

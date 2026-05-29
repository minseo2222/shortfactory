from __future__ import annotations

import unicodedata
from pathlib import Path


BLOCKED_TEXT_CHARS = {
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
    "\u2028": "LINE SEPARATOR",
    "\u2029": "PARAGRAPH SEPARATOR",
    "\u0085": "NEXT LINE",
}


def _selected_text_paths() -> list[Path]:
    explicit_paths = [
        Path(".gitattributes"),
        Path(".env.example"),
        Path("README.md"),
        Path("AGENTS.md"),
        Path("pyproject.toml"),
        Path(".github/workflows/ci.yml"),
    ]
    discovered_paths = [
        *Path("docs").rglob("*.md"),
        *Path("src").rglob("*.py"),
        *Path("tests").rglob("*.py"),
        *Path("tests").rglob("*.json"),
        *Path("schemas").rglob("*.md"),
        *Path("templates").rglob("*.json"),
        *Path("templates").rglob("*.kdenlive"),
    ]
    return sorted({path for path in [*explicit_paths, *discovered_paths] if path.is_file()})


def _python_paths() -> list[Path]:
    return sorted([*Path("src").rglob("*.py"), *Path("tests").rglob("*.py")])


def test_selected_text_files_use_lf_line_endings() -> None:
    failures: list[str] = []

    for path in _selected_text_paths():
        data = path.read_bytes()
        if b"\r\n" in data:
            failures.append(f"{path.as_posix()}: contains CRLF line endings")
        elif b"\r" in data:
            failures.append(f"{path.as_posix()}: contains CR-only line endings")

    assert not failures, "\n".join(failures)


def test_selected_text_files_do_not_contain_hidden_or_format_controls() -> None:
    failures: list[str] = []

    for path in _selected_text_paths():
        text = path.read_text(encoding="utf-8")
        for index, char in enumerate(text):
            category = unicodedata.category(char)
            if char not in BLOCKED_TEXT_CHARS and category != "Cf":
                continue
            line_no = text.count("\n", 0, index) + 1
            line_start = text.rfind("\n", 0, index) + 1
            column_no = index - line_start + 1
            label = BLOCKED_TEXT_CHARS.get(
                char,
                f"{category} {unicodedata.name(char, 'UNKNOWN')}",
            )
            failures.append(
                f"{path.as_posix()}:{line_no}:{column_no}: U+{ord(char):04X} {label}"
            )

    assert not failures, "\n".join(failures)


def test_python_files_are_not_single_giant_lines() -> None:
    failures: list[str] = []

    for path in _python_paths():
        text = path.read_text(encoding="utf-8")
        line_count = text.count("\n") + 1
        if len(text.strip()) > 1000 and line_count < 5:
            failures.append(
                f"{path.as_posix()}: {len(text.strip())} non-whitespace chars "
                f"across only {line_count} lines"
            )

    assert not failures, "\n".join(failures)

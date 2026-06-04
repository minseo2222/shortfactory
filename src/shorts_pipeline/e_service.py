"""Phase 5 E script/title generation skeleton."""

from __future__ import annotations

import json
import re
import sqlite3
import string
import unicodedata
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from shorts_pipeline.config import KST
from shorts_pipeline.d_service import assert_d_image_manifest_ready_for_e
from shorts_pipeline.db import connect_db, init_db, insert_project_status_event
from shorts_pipeline.llm.e_provider import EScriptProvider
from shorts_pipeline.models import DImageManifest, EScript, SourceArtifact, TimelineJson
from shorts_pipeline.security import (
    ensure_path_under_root,
    ensure_relative_project_path,
    sha256_file,
)
from shorts_pipeline.state_machine import assert_transition_allowed

DEFAULT_E_PROMPT_VERSION = "e_script_prompt.v2.1.001"
E_SCHEMA_VERSION = "e_script.v2.1"
REQUIRED_CURRENT_STATUS = "images_inserted"
SCRIPT_GENERATED_STATUS = "script_generated"

FORBIDDEN_E_KEYS = (
    "full_text",
    "raw_html",
    "comments",
    "comment_dump",
    "screenshot",
    "cookie",
    "api_key",
    "secret",
    "password",
    "token",
)
FORBIDDEN_E_STORAGE_VALUE_TERMS = (
    "full_text",
    "raw_html",
    "comment_dump",
    "cookie",
    "api_key",
    "secret",
    "password",
    "token",
)
DIRECT_SOURCE_PHRASES = (
    "댓글에 따르면",
    "원문 그대로",
    "캡처를 보면",
    "게시글 원문",
    "실명",
    "닉네임",
    "본명",
    "comment says",
    "as the comment says",
    "raw source",
    "verbatim source",
    "original post says",
    "real name",
    "nickname",
)
HARD_OVERCLAIM_TERMS = (
    "확정",
    "무조건",
    "100%",
    "실명 공개",
    "범인",
    "범죄자",
    "사기꾼",
    "가해자",
    "피해자",
    "유죄",
    "진범",
    "confirmed",
    "criminal",
    "scammer",
    "perpetrator",
    "victim",
    "guilty",
    "fraudster",
    "thief",
    "culprit",
)
IDENTITY_TERMS = (
    "실명",
    "닉네임",
    "본명",
    "real name",
    "nickname",
)
METADATA_TERMS = (
    "exif",
    "gps",
    "ocr",
    "facial recognition",
    "face recognition",
    "얼굴 인식",
    "위치정보",
)
# Heuristic mockery/hate guard applied to titles and narration scripts only.
# Terms are chosen to avoid substring collisions with neutral words (for
# example, "비하" is excluded because it appears inside "준비하다").
DEROGATORY_TERMS = (
    "멍청",
    "한심",
    "찌질",
    "병신",
    "등신",
    "또라이",
    "머저리",
    "쓰레기 같",
    "조롱하",
    "혐오스",
    "idiot",
    "stupid",
    "moron",
    "pathetic",
    "scumbag",
    "clown",
    "loser",
)
CLAIM_GUARD_CATEGORIES = (
    ("real names or nicknames", ("실명", "닉네임", "본명", "real name", "nickname")),
    ("personal information", ("개인정보", "personal information", "personal info")),
    ("crime assertion", ("범죄", "crime assertion", "crime", "criminal")),
    ("fabricated numbers", ("허위 수치", "fabricated number", "unsupported number")),
    ("direct source quotation", ("원문 직접 인용", "direct quote", "source quote")),
    (
        "original screenshot/capture reuse",
        ("원본 캡처", "original screenshot", "original capture", "screenshot reuse"),
    ),
)


class ProviderNotConfiguredError(ValueError):
    """Raised when E generation is requested without an injected provider."""


class ProjectNotFoundError(ValueError):
    """Raised when a project row does not exist."""


class ProjectStatusError(ValueError):
    """Raised when the project is not in the required status."""


class EScriptInputError(ValueError):
    """Raised when source, timeline, or D input is missing or invalid."""


class EScriptValidationError(ValueError):
    """Raised when a parsed E script fails application-level validation."""


class EScriptGenerationError(ValueError):
    """Raised when all provider attempts fail validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        joined = "; ".join(errors)
        super().__init__(f"E script generation failed validation: {joined}")


def _now_kst(clock: Callable[[], datetime] | None = None) -> datetime:
    current = clock() if clock else datetime.now(tz=KST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=KST)
    return current.astimezone(KST).replace(microsecond=0)


def _load_project_row(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ProjectNotFoundError(f"project not found: {project_id}")
    return row


def _resolve_project_dir(projects_root: Path, project_row: sqlite3.Row) -> Path:
    relative_project_dir = ensure_relative_project_path(project_row["project_dir"])
    root = Path(projects_root).resolve()
    return ensure_path_under_root(root, root / relative_project_dir)


def _load_source_artifact(project_dir: Path, project_id: str) -> SourceArtifact:
    source_path = ensure_path_under_root(project_dir, project_dir / "source.json")
    if not source_path.exists():
        raise EScriptInputError("source.json is missing")
    source = SourceArtifact.model_validate(json.loads(source_path.read_text(encoding="utf-8")))
    if source.project_id != project_id:
        raise EScriptInputError("source.json project_id does not match project row")
    return source


def _load_timeline(project_dir: Path, project_id: str) -> TimelineJson:
    timeline_path = ensure_path_under_root(project_dir, project_dir / "timeline.json")
    if not timeline_path.exists():
        raise EScriptInputError("timeline.json is missing")
    timeline = TimelineJson.model_validate(json.loads(timeline_path.read_text(encoding="utf-8")))
    if timeline.project_id != project_id:
        raise EScriptInputError("timeline.json project_id does not match project row")
    return timeline


def _snapshot_file(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _restore_file(path: Path, snapshot: bytes | None) -> None:
    if snapshot is None:
        if path.exists():
            path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(snapshot)


def _iter_key_value_strings(value: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            found.append(("key", str(key)))
            found.extend(_iter_key_value_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_key_value_strings(child))
    elif isinstance(value, str):
        found.append(("value", value))
    return found


def _normalize_for_copy_check(text: str) -> str:
    without_punctuation = "".join(
        char for char in text if not char.isspace() and char not in string.punctuation
    )
    return without_punctuation.casefold()


def _normalize_basis(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).casefold()


def _summarize_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ")
    return text[:500]


def _normalize_guard_text(text: str) -> str:
    """Normalize text before safety matching to defeat simple obfuscation.

    Applies NFKC (so full-width/compatibility variants fold to plain forms) and
    drops zero-width / format (Unicode category ``Cf``) characters that are used
    to split a forbidden term (e.g. a zero-width space inserted between
    syllables). Returns casefolded text.
    """
    normalized = unicodedata.normalize("NFKC", text)
    cleaned = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
    return cleaned.casefold()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    """True if any term appears in the text, tolerant of obfuscation.

    Beyond a direct normalized substring match, a whitespace-tolerant pass
    allows the term's (non-space) characters to be separated by whitespace
    (e.g. ``멍 청``). Safety-first: this can over-match in rare cases, which is
    preferred over letting a spaced/zero-width variant slip through.
    """
    normalized = _normalize_guard_text(text)
    for term in terms:
        term_norm = _normalize_guard_text(term)
        if not term_norm:
            continue
        if term_norm in normalized:
            return True
        spaced = r"\s*".join(re.escape(ch) for ch in term_norm if not ch.isspace())
        if spaced and re.search(spaced, normalized):
            return True
    return False


def _safe_allowed_context_texts(
    *,
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
) -> list[str]:
    texts = _iter_key_value_strings(source.model_dump(mode="json"))
    texts.extend(_iter_key_value_strings(timeline.model_dump(mode="json")))
    texts.extend(_iter_key_value_strings(d_manifest.model_dump(mode="json")))
    return [text for _kind, text in texts]


def _validate_no_forbidden_fields(script: EScript) -> None:
    for kind, text in _iter_key_value_strings(script.model_dump(mode="json")):
        lowered = text.casefold()
        if kind == "key" and any(term in lowered for term in FORBIDDEN_E_KEYS):
            raise EScriptValidationError("E script contains forbidden raw-source keys")
        if kind == "value" and any(term in lowered for term in FORBIDDEN_E_STORAGE_VALUE_TERMS):
            raise EScriptValidationError("E script contains forbidden raw-source terms")
        if kind == "value" and _contains_any(text, METADATA_TERMS):
            raise EScriptValidationError("E script must not reference EXIF/GPS/OCR/face metadata")
        if kind == "value":
            if re.search(r"https?://", text, flags=re.IGNORECASE):
                raise EScriptValidationError("E script must not contain external URLs")
            if re.search(r"[A-Za-z]:[\\/]", text) or text.startswith(("/", "\\")):
                raise EScriptValidationError("E script must not contain absolute paths")
            if "../" in text or "..\\" in text:
                raise EScriptValidationError("E script must not contain path traversal")


def _validate_no_direct_copy(
    generated_texts: list[str],
    *,
    source: SourceArtifact,
) -> None:
    metadata = [
        source.source_title,
        source.user_or_llm_summary,
        source.hook,
        source.why_shortable,
    ]
    normalized_metadata = [_normalize_for_copy_check(text) for text in metadata]
    for generated in generated_texts:
        normalized = _normalize_for_copy_check(generated)
        if len(normalized) >= 12 and any(normalized in meta for meta in normalized_metadata):
            raise EScriptValidationError("E script/title looks copied from source metadata")


def _validate_forbidden_claims(script: EScript) -> None:
    joined_claims = " ".join(script.forbidden_claims).casefold()
    for label, terms in CLAIM_GUARD_CATEGORIES:
        if not any(term.casefold() in joined_claims for term in terms):
            raise EScriptValidationError(f"forbidden_claims must warn against {label}")


def _validate_title_safety(
    script: EScript,
    *,
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
) -> None:
    titles = [candidate.title for candidate in script.title_candidates]
    if script.recommended_title not in titles:
        raise EScriptValidationError("recommended_title must be one of title_candidates")
    if len(titles) != len(set(titles)):
        raise EScriptValidationError("title candidates must be unique")

    context_text = " ".join(
        _safe_allowed_context_texts(source=source, timeline=timeline, d_manifest=d_manifest)
    )
    allowed_numbers = set(re.findall(r"\d+", context_text))

    for title in titles:
        title_numbers = set(re.findall(r"\d+", title))
        unsupported_numbers = title_numbers - allowed_numbers
        if unsupported_numbers:
            raise EScriptValidationError("title contains unsupported numeric claims")
        if _contains_any(title, HARD_OVERCLAIM_TERMS):
            raise EScriptValidationError("title contains hard factual overclaims")
        if _contains_any(title, IDENTITY_TERMS):
            raise EScriptValidationError("title must not identify names or nicknames")
        if _contains_any(title, DEROGATORY_TERMS):
            raise EScriptValidationError("title must not mock or demean individuals")


def _basis_is_connected(
    basis_items: list[str],
    *,
    scene_fact_basis: list[str],
    scene_avoid_claims: list[str],
    image_note: str | None,
) -> bool:
    # A narration fact_basis must be grounded in THIS scene's own fact_basis,
    # avoid_claims, or D image note. The previous generic-term shortcut (passing
    # any basis containing "timeline"/"image"/"source"/etc.) let fabricated
    # narration attach to any scene, so it is removed: at least one basis item
    # must genuinely overlap the scene's allowed content.
    allowed_items = [*scene_fact_basis, *scene_avoid_claims]
    if image_note:
        allowed_items.append(image_note)
    allowed_norms = [_normalize_basis(item) for item in allowed_items if item]
    for basis in basis_items:
        basis_norm = _normalize_basis(basis)
        if any(
            basis_norm and allowed and (basis_norm in allowed or allowed in basis_norm)
            for allowed in allowed_norms
        ):
            return True
    return False


def _validate_narration_safety(
    script: EScript,
    *,
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
) -> None:
    expected_scene_ids = [scene.scene_id for scene in timeline.scenes]
    actual_scene_ids = [line.scene_id for line in script.narration_script]
    if actual_scene_ids != expected_scene_ids:
        raise EScriptValidationError("narration scene order must match timeline scenes")
    if len(actual_scene_ids) != len(set(actual_scene_ids)):
        raise EScriptValidationError("narration scene IDs must not contain duplicates")

    allowed_numbers = set(
        re.findall(
            r"\d+",
            " ".join(
                _safe_allowed_context_texts(
                    source=source, timeline=timeline, d_manifest=d_manifest
                )
            ),
        )
    )
    slots_by_scene = {slot.scene_id: slot for slot in d_manifest.slots}
    for line, scene in zip(script.narration_script, timeline.scenes, strict=True):
        if not line.fact_basis:
            raise EScriptValidationError(f"{line.scene_id} requires fact_basis")
        slot = slots_by_scene.get(line.scene_id)
        image_note = slot.actual_image_note if slot else None
        if not _basis_is_connected(
            line.fact_basis,
            scene_fact_basis=scene.fact_basis,
            scene_avoid_claims=scene.avoid_claims,
            image_note=image_note,
        ):
            raise EScriptValidationError(f"{line.scene_id} fact_basis is not connected")
        if len(line.script.strip()) > scene.duration_sec * 20 + 40:
            raise EScriptValidationError(f"{line.scene_id} narration is too long to speak")
        if _contains_any(line.script, DIRECT_SOURCE_PHRASES):
            raise EScriptValidationError("narration must not quote comments or raw source text")
        if _contains_any(line.script, DEROGATORY_TERMS):
            raise EScriptValidationError("narration must not mock or demean individuals")
        if _contains_any(line.script, HARD_OVERCLAIM_TERMS):
            raise EScriptValidationError("narration must not assert guilt or hard overclaims")
        if _contains_any(line.script, IDENTITY_TERMS):
            raise EScriptValidationError("narration must not identify names or nicknames")
        if set(re.findall(r"\d+", line.script)) - allowed_numbers:
            raise EScriptValidationError(f"{line.scene_id} narration has unsupported numbers")


def validate_e_script_against_inputs(
    script: EScript,
    *,
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
) -> None:
    """Apply deterministic E validation rules beyond Pydantic field checks."""
    if script.schema_version != E_SCHEMA_VERSION:
        raise EScriptValidationError("schema_version must be e_script.v2.1")
    if len(script.narration_script) != len(timeline.scenes):
        raise EScriptValidationError("narration line count must match timeline scene count")
    if timeline.project_id != source.project_id or d_manifest.project_id != timeline.project_id:
        raise EScriptValidationError("source, timeline, and D manifest project IDs must match")

    _validate_narration_safety(
        script, source=source, timeline=timeline, d_manifest=d_manifest
    )
    _validate_title_safety(script, source=source, timeline=timeline, d_manifest=d_manifest)
    _validate_forbidden_claims(script)
    _validate_no_direct_copy(
        [
            line.script
            for line in script.narration_script
        ]
        + [candidate.title for candidate in script.title_candidates],
        source=source,
    )
    _validate_no_forbidden_fields(script)


def build_e_generation_context(
    *,
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
) -> dict[str, Any]:
    """Build the safe minimal context for injected E providers."""
    source_data = source.model_dump(mode="json")
    return {
        "project_id": source.project_id,
        "timeline_json": timeline.model_dump(mode="json"),
        "d_image_manifest": d_manifest.model_dump(mode="json"),
        "source_reference": {
            "source_url": source_data["source_url"],
            "source_community": source_data["source_community"],
            "source_title": source_data["source_title"],
            "summary": source_data["user_or_llm_summary"],
            "hook": source_data["hook"],
            "why_shortable": source_data["why_shortable"],
            "risk_flags_for_user": source_data["risk_flags_for_user"],
        },
        "voice_policy": {
            "user_records_voice": True,
            "script_should_be_speakable": True,
            "strict_timecode": False,
        },
        "title_policy": {
            "style": "shorts_clickable",
            "intensity": "high",
            "do_not_fabricate": True,
        },
    }


def _parse_and_validate_provider_payload(
    payload: dict[str, Any],
    *,
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
) -> EScript:
    script = EScript.model_validate(payload)
    validate_e_script_against_inputs(
        script,
        source=source,
        timeline=timeline,
        d_manifest=d_manifest,
    )
    return script


def _validate_with_retries(
    *,
    context: dict[str, Any],
    source: SourceArtifact,
    timeline: TimelineJson,
    d_manifest: DImageManifest,
    provider: EScriptProvider,
    prompt_version: str,
    max_retries: int,
) -> EScript:
    previous_errors: list[str] = []
    total_attempts = max_retries + 1
    for _attempt in range(total_attempts):
        payload = provider.generate(
            context=context,
            prompt_version=prompt_version,
            previous_errors=list(previous_errors),
        )
        try:
            return _parse_and_validate_provider_payload(
                payload,
                source=source,
                timeline=timeline,
                d_manifest=d_manifest,
            )
        except (ValidationError, EScriptValidationError) as exc:
            previous_errors.append(_summarize_error(exc))

    raise EScriptGenerationError(previous_errors)


def write_e_script_json(project_dir: str | Path, script: EScript) -> Path:
    """Write and re-validate the E script/title artifact."""
    root = Path(project_dir).resolve()
    output_path = ensure_path_under_root(root, root / "e_script.json")
    data = script.model_dump(mode="json")
    output_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    EScript.model_validate(json.loads(output_path.read_text(encoding="utf-8")))
    return output_path


def generate_e_script(
    project_id: str,
    *,
    db_path: Path,
    projects_root: Path,
    provider: EScriptProvider | None,
    clock: Callable[[], datetime] | None = None,
    prompt_version: str = DEFAULT_E_PROMPT_VERSION,
    max_retries: int = 2,
) -> EScript:
    """Generate, validate, persist, and mark an E script/title artifact."""
    if provider is None:
        raise ProviderNotConfiguredError("E script provider must be injected")
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")

    conn = connect_db(db_path)
    output_path: Path | None = None
    previous_output: bytes | None = None
    try:
        init_db(conn)
        project_row = _load_project_row(conn, project_id)
        if project_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("E generation requires images_inserted status")
        project_dir = _resolve_project_dir(projects_root, project_row)
        source = _load_source_artifact(project_dir, project_id)
        timeline = _load_timeline(project_dir, project_id)
        d_manifest = assert_d_image_manifest_ready_for_e(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
        )
        context = build_e_generation_context(
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
        )
        script = _validate_with_retries(
            context=context,
            source=source,
            timeline=timeline,
            d_manifest=d_manifest,
            provider=provider,
            prompt_version=prompt_version,
            max_retries=max_retries,
        )

        output_path = ensure_path_under_root(project_dir, project_dir / "e_script.json")
        previous_output = _snapshot_file(output_path)
        artifact_relative_path = ensure_relative_project_path(f"{project_id}/e_script.json").as_posix()

        conn.execute("BEGIN")
        current_row = _load_project_row(conn, project_id)
        if current_row["status"] != REQUIRED_CURRENT_STATUS:
            raise ProjectStatusError("project status changed before E persistence")
        assert_transition_allowed(current_row["status"], SCRIPT_GENERATED_STATUS)

        written_path = write_e_script_json(project_dir, script)
        digest = sha256_file(written_path)
        created_at = _now_kst(clock).isoformat()

        llm_cursor = conn.execute(
            """
            INSERT INTO llm_runs (
                project_id,
                stage,
                provider,
                model_name,
                prompt_version,
                schema_version,
                status,
                error_code,
                input_tokens,
                output_tokens,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                "E",
                getattr(provider, "provider_name", "fake"),
                getattr(provider, "model_name", "mock-e-script-v2.1"),
                prompt_version,
                E_SCHEMA_VERSION,
                "succeeded",
                None,
                None,
                None,
                created_at,
            ),
        )
        llm_run_id = llm_cursor.lastrowid
        conn.execute(
            """
            INSERT INTO scripts (
                project_id,
                schema_version,
                llm_run_id,
                narration_json,
                title_candidates_json,
                recommended_title,
                artifact_path,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                E_SCHEMA_VERSION,
                llm_run_id,
                json.dumps(
                    [line.model_dump(mode="json") for line in script.narration_script],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                json.dumps(
                    [candidate.model_dump(mode="json") for candidate in script.title_candidates],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                script.recommended_title,
                artifact_relative_path,
                created_at,
            ),
        )
        conn.execute(
            """
            INSERT INTO artifacts (
                project_id,
                artifact_type,
                relative_path,
                sha256,
                created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, "e_script", artifact_relative_path, digest, created_at),
        )
        conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (SCRIPT_GENERATED_STATUS, created_at, project_id),
        )
        insert_project_status_event(
            conn,
            project_id=project_id,
            from_status=current_row["status"],
            to_status=SCRIPT_GENERATED_STATUS,
            stage="E",
            reason="script_generated",
            created_at=created_at,
        )
        conn.commit()
        return script
    except Exception:
        conn.rollback()
        if output_path is not None:
            _restore_file(output_path, previous_output)
        raise
    finally:
        conn.close()

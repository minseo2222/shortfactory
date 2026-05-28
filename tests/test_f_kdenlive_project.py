from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from shorts_pipeline.db import connect_db
from shorts_pipeline.dev_fakes import DevFakeBProvider, DevFakeEProvider
from shorts_pipeline.d_service import DImageManifestValidationError
from shorts_pipeline.f_service import (
    FKdenliveInputError,
    FKdenliveValidationError,
    ProjectStatusError,
    generate_f_kdenlive_project,
    validate_generated_kdenlive_xml,
)
from shorts_pipeline.models import (
    DImageManifest,
    EScript,
    FKdenliveManifest,
    TimelineJson,
)
from shorts_pipeline.security import ensure_relative_project_path, sha256_file
from shorts_pipeline.smoke import run_local_smoke_pipeline


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


def run_script_generated_project(tmp_path) -> tuple[Path, Path, str]:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    result = run_local_smoke_pipeline(
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
        b_provider=DevFakeBProvider(),
        e_provider=DevFakeEProvider(),
    )
    return db_path, projects_root, result.project_id


def project_dir(projects_root: Path, project_id: str) -> Path:
    return projects_root / project_id


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_timeline(projects_root: Path, project_id: str) -> TimelineJson:
    return TimelineJson.model_validate(
        load_json(project_dir(projects_root, project_id) / "timeline.json")
    )


def load_d_manifest(projects_root: Path, project_id: str) -> DImageManifest:
    return DImageManifest.model_validate(
        load_json(project_dir(projects_root, project_id) / "d_image_manifest.json")
    )


def load_e_script(projects_root: Path, project_id: str) -> EScript:
    return EScript.model_validate(
        load_json(project_dir(projects_root, project_id) / "e_script.json")
    )


def fetch_all(db_path: Path, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = connect_db(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def project_status(db_path: Path, project_id: str) -> str:
    rows = fetch_all(db_path, "SELECT status FROM projects WHERE id = ?", (project_id,))
    assert len(rows) == 1
    return rows[0]["status"]


def f_output_paths(projects_root: Path, project_id: str) -> list[Path]:
    root = project_dir(projects_root, project_id)
    return [
        root / "project.kdenlive",
        root / "f_kdenlive_manifest.json",
        root / "notes" / "manual_kdenlive_editing.md",
    ]


def assert_no_f_outputs_or_artifacts(db_path: Path, projects_root: Path, project_id: str) -> None:
    for path in f_output_paths(projects_root, project_id):
        assert not path.exists()
    assert (
        fetch_all(
            db_path,
            """
            SELECT artifact_type
            FROM artifacts
            WHERE project_id = ?
              AND artifact_type IN (
                'kdenlive_project',
                'f_kdenlive_manifest',
                'manual_kdenlive_editing_guide'
              )
            """,
            (project_id,),
        )
        == []
    )


def xml_tree(projects_root: Path, project_id: str) -> ET.ElementTree:
    return ET.parse(project_dir(projects_root, project_id) / "project.kdenlive")


def xml_resources(tree: ET.ElementTree) -> list[str]:
    resources: list[str] = []
    for producer in tree.getroot().findall("producer"):
        for element in producer.findall("property"):
            if element.attrib.get("name") == "resource":
                resources.append(element.text or "")
    return resources


def test_happy_path_generates_f_files_artifacts_and_keeps_status(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    timeline = load_timeline(projects_root, project_id)

    manifest = generate_f_kdenlive_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert isinstance(manifest, FKdenliveManifest)
    root = project_dir(projects_root, project_id)
    assert (root / "project.kdenlive").is_file()
    assert (root / "f_kdenlive_manifest.json").is_file()
    assert (root / "notes" / "manual_kdenlive_editing.md").is_file()
    reloaded_manifest = FKdenliveManifest.model_validate(
        load_json(root / "f_kdenlive_manifest.json")
    )
    assert reloaded_manifest == manifest
    assert manifest.project_id == project_id
    assert len(manifest.scenes) == len(timeline.scenes)
    assert manifest.external_template_used is False
    assert manifest.rendering_performed is False

    tree = xml_tree(projects_root, project_id)
    xml_root = tree.getroot()
    assert xml_root.tag == "mlt"
    profile = xml_root.find("profile")
    assert profile is not None
    assert profile.attrib["width"] == "1080"
    assert profile.attrib["height"] == "1920"
    assert profile.attrib["frame_rate_num"] == "30"
    assert profile.attrib["frame_rate_den"] == "1"

    for scene in manifest.scenes:
        for relative_path in (scene.image_path, scene.text_overlay_path):
            safe_path = ensure_relative_project_path(relative_path)
            assert not safe_path.is_absolute()
            assert ".." not in safe_path.parts
            assert (root / safe_path).is_file()

    artifact_rows = fetch_all(
        db_path,
        """
        SELECT artifact_type, relative_path, sha256
        FROM artifacts
        WHERE project_id = ?
          AND artifact_type IN (
            'kdenlive_project',
            'f_kdenlive_manifest',
            'manual_kdenlive_editing_guide'
          )
        """,
        (project_id,),
    )
    assert {row["artifact_type"] for row in artifact_rows} == {
        "kdenlive_project",
        "f_kdenlive_manifest",
        "manual_kdenlive_editing_guide",
    }
    for row in artifact_rows:
        relative_path = ensure_relative_project_path(row["relative_path"])
        assert row["relative_path"].startswith(f"{project_id}/")
        assert row["sha256"] == sha256_file(projects_root / relative_path)

    assert project_status(db_path, project_id) == "script_generated"


def test_xml_references_d_actual_images_and_timeline_text_overlays(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    timeline = load_timeline(projects_root, project_id)
    d_manifest = load_d_manifest(projects_root, project_id)

    generate_f_kdenlive_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    resources = set(xml_resources(xml_tree(projects_root, project_id)))
    expected_images = {slot.actual_image_path for slot in d_manifest.slots}
    expected_text_overlays = {scene.text_overlay_path for scene in timeline.scenes}
    assert expected_images.issubset(resources)
    assert expected_text_overlays.issubset(resources)
    assert not any(
        resource.startswith("assets/placeholders/")
        for resource in resources
        if resource not in expected_images
    )


def test_frame_calculation_is_deterministic(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    timeline = load_timeline(projects_root, project_id)

    manifest = generate_f_kdenlive_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    assert manifest.total_frames == round(timeline.total_duration_sec * 30)
    for manifest_scene, timeline_scene in zip(manifest.scenes, timeline.scenes, strict=True):
        assert manifest_scene.start_frame == round(timeline_scene.start_sec * 30)
        assert manifest_scene.duration_frames == round(timeline_scene.duration_sec * 30)


def test_manual_guide_includes_required_safety_notes(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    timeline = load_timeline(projects_root, project_id)
    d_manifest = load_d_manifest(projects_root, project_id)

    generate_f_kdenlive_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    guide = (
        project_dir(projects_root, project_id)
        / "notes"
        / "manual_kdenlive_editing.md"
    ).read_text(encoding="utf-8")
    assert project_id in guide
    assert "project.kdenlive" in guide
    assert "No rendering was performed" in guide
    assert "No upload was performed" in guide
    assert "No TTS or voice synthesis was performed" in guide
    assert "d_image_manifest.json" in guide
    assert "rights" in guide.casefold()
    for scene in timeline.scenes:
        assert scene.scene_id in guide
        assert scene.text_overlay_path in guide
    for slot in d_manifest.slots:
        assert slot.actual_image_path in guide


@pytest.mark.parametrize(
    "status",
    [
        "candidate_selected",
        "planned",
        "project_generated",
        "waiting_for_user_images",
        "images_inserted",
    ],
)
def test_wrong_status_is_blocked_without_f_outputs(tmp_path, status: str) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    conn = connect_db(db_path)
    try:
        conn.execute("UPDATE projects SET status = ? WHERE id = ?", (status, project_id))
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ProjectStatusError):
        generate_f_kdenlive_project(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == status


def test_missing_e_script_is_blocked_without_f_outputs(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    (project_dir(projects_root, project_id) / "e_script.json").unlink()

    with pytest.raises(FKdenliveInputError):
        generate_f_kdenlive_project(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == "script_generated"


def test_d_readiness_failure_is_blocked_without_f_outputs(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    manifest_path = project_dir(projects_root, project_id) / "d_image_manifest.json"
    payload = load_json(manifest_path)
    payload["slots"][0]["rights_confirmed_by_user"] = False
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(DImageManifestValidationError):
        generate_f_kdenlive_project(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == "script_generated"


@pytest.mark.parametrize("unsafe_path", ["../evil.png", "/tmp/evil.png", "https://example.com/evil.png"])
def test_unsafe_input_paths_are_blocked(tmp_path, unsafe_path: str) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    timeline_path = project_dir(projects_root, project_id) / "timeline.json"
    payload = load_json(timeline_path)
    payload["scenes"][0]["text_overlay_path"] = unsafe_path
    timeline_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises((ValidationError, FKdenliveValidationError)):
        generate_f_kdenlive_project(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == "script_generated"


def test_external_template_is_not_used(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    manifest = generate_f_kdenlive_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )

    xml_text = (project_dir(projects_root, project_id) / "project.kdenlive").read_text(
        encoding="utf-8"
    )
    assert manifest.external_template_used is False
    assert "kdenlive_vertical_1080x1920_30fps.kdenlive" not in xml_text
    assert "TEMPLATE_METADATA" not in xml_text


@pytest.mark.parametrize(
    "forbidden_term",
    ["raw_html", "comments", "screenshot", "api_key", "secret", "token"],
)
def test_xml_forbidden_terms_are_blocked(tmp_path, forbidden_term: str) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)
    manifest = generate_f_kdenlive_project(
        project_id,
        db_path=db_path,
        projects_root=projects_root,
        clock=fixed_clock,
    )
    xml_path = project_dir(projects_root, project_id) / "project.kdenlive"
    tree = ET.parse(xml_path)
    ET.SubElement(tree.getroot(), "property", {"name": forbidden_term}).text = "blocked"
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    with pytest.raises(FKdenliveValidationError):
        validate_generated_kdenlive_xml(
            xml_path,
            project_root=project_dir(projects_root, project_id),
            manifest=manifest,
        )


def test_file_write_failure_rolls_back_f_outputs_and_db_state(tmp_path, monkeypatch) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    def fail_write(*args, **kwargs):
        raise OSError("simulated F manifest write failure")

    monkeypatch.setattr("shorts_pipeline.f_service.write_f_manifest_json", fail_write)

    with pytest.raises(OSError):
        generate_f_kdenlive_project(
            project_id,
            db_path=db_path,
            projects_root=projects_root,
            clock=fixed_clock,
        )

    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)
    assert project_status(db_path, project_id) == "script_generated"


def test_smoke_path_remains_unchanged_and_does_not_generate_f(tmp_path) -> None:
    db_path, projects_root, project_id = run_script_generated_project(tmp_path)

    assert project_status(db_path, project_id) == "script_generated"
    assert_no_f_outputs_or_artifacts(db_path, projects_root, project_id)

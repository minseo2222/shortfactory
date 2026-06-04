"""Multi-sample A->F smoke coverage (docs/05 Phase 6 completion criterion).

Runs twelve distinct synthetic candidates with varied valid scene plans
(3-6 scenes, different styles/durations) through the full deterministic
A->F path and asserts, for each, that:

- the project reaches ``script_generated``;
- the timeline and E narration match the scene count;
- ``project.kdenlive`` parses and declares a vertical 1080x1920 30fps profile;
- every referenced media resource exists on disk (no missing media);
- the F manifest declares the fixed vertical canvas.

No real providers or network are used; B uses a per-sample fixed provider and E
uses the deterministic fake provider.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, get_args

import pytest

from shorts_pipeline.b_service import SAFETY_GUARD_TERMS, generate_b_scene_plan
from shorts_pipeline.c_service import compile_c_project
from shorts_pipeline.d_service import confirm_d_image_manifest, initialize_d_image_manifest
from shorts_pipeline.dev_fakes import DevFakeEProvider
from shorts_pipeline.e_service import generate_e_script
from shorts_pipeline.f_service import generate_f_kdenlive_project
from shorts_pipeline.models import ShortsStyle, SourceArtifact, TimelineJson
from shorts_pipeline.project_service import create_project_from_candidate

# scene_count -> per-scene duration giving a 30-60s total within target +/- 5.
# BScenePlan requires at least 4 scenes, so counts range over 4-6.
DURATION_BY_COUNT = {4: 10.0, 5: 9.0, 6: 8.0}
STYLES = list(get_args(ShortsStyle))


def fixed_clock() -> datetime:
    return datetime(2026, 5, 29, 10, 30, 0)


class VariedBProvider:
    provider_name = "fake"
    model_name = "mock-b-scene-plan-v2.1"

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def generate(self, *, source: SourceArtifact, prompt_version: str, previous_errors: list[str]):
        return json.loads(json.dumps(self._payload))


def make_candidate(idx: int) -> dict[str, Any]:
    return {
        "candidate_id": f"sample-{idx:02d}",
        "title": f"Fictional safe topic number {idx}",
        "source_url": f"https://example.com/community/post/{1000 + idx}",
        "community": ["manual", "forum-a", "forum-b"][idx % 3],
        "collected_at": "2026-06-01T09:00:00+09:00",
        "summary": f"A neutral fictional summary variant {idx} with no identities.",
        "hook": f"A neutral hook variant {idx}.",
        "why_shortable": f"A neutral rationale variant {idx}.",
        "risk_flags_for_user": [],
        "status": "selected",
    }


def make_b_payload(n_scenes: int, style_idx: int) -> dict[str, Any]:
    per = DURATION_BY_COUNT[n_scenes]
    total = per * n_scenes
    scenes = []
    for i in range(1, n_scenes + 1):
        if i == 1:
            purpose = "hook"
        elif i == n_scenes:
            purpose = "payoff"
        else:
            purpose = "context"
        scenes.append(
            {
                "scene_id": f"s{i:02d}",
                "duration_sec": per,
                "purpose": purpose,
                "screen_text": f"Point {i}",
                "visual_direction": f"Neutral composition for scene {i}.",
                "image_slot_description": f"Neutral abstract image for scene {i}.",
                "narration_intent": f"Explain scene {i} from safe metadata only.",
                "source_basis": [f"fictional summary point {i}"],
                "do_not_say": [
                    f"{SAFETY_GUARD_TERMS[0]} 추정 금지",
                    f"{SAFETY_GUARD_TERMS[3]} 금지",
                ],
            }
        )
    return {
        "schema_version": "b_scene_plan.v2.1",
        "selected_style": STYLES[style_idx % len(STYLES)],
        "style_reason": "A concise structure fits this fictional sample.",
        "target_duration_sec": total,
        "scene_plan": scenes,
        "risk_flags": ["identity inference prohibited", "direct quotation prohibited"],
    }


def ready_d_payload(timeline: TimelineJson) -> dict[str, Any]:
    return {
        "schema_version": "d_image_manifest.v2.1",
        "project_id": timeline.project_id,
        "image_insert_completed": True,
        "user_confirmed": True,
        "completed_at": None,
        "slots": [
            {
                "slot_id": scene.image_slot_id,
                "scene_id": scene.scene_id,
                "status": "replaced",
                "planned_image_path": scene.image_path,
                "actual_image_path": scene.image_path,
                "actual_image_note": f"User-owned safe image for {scene.scene_id}.",
                "source_type": "user_owned",
                "rights_confirmed_by_user": True,
                "contains_face": False,
                "face_rights_confirmed": None,
                "contains_personal_info": False,
                "contains_original_capture": False,
                "contains_community_logo": False,
                "image_sha256": None,
            }
            for scene in timeline.scenes
        ],
        "warnings": [],
    }


def _status(db_path: Path, project_id: str) -> str:
    from shorts_pipeline.db import connect_readonly_db

    conn = connect_readonly_db(db_path)
    try:
        return conn.execute("SELECT status FROM projects WHERE id = ?", (project_id,)).fetchone()[0]
    finally:
        conn.close()


SAMPLES = [(idx, [4, 5, 6][idx % 3]) for idx in range(12)]


@pytest.mark.parametrize("idx,n_scenes", SAMPLES)
def test_multisample_a_to_f(idx: int, n_scenes: int, tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"

    project = create_project_from_candidate(
        make_candidate(idx), db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    pid = project.project_id

    generate_b_scene_plan(
        pid,
        db_path=db_path,
        projects_root=projects_root,
        provider=VariedBProvider(make_b_payload(n_scenes, idx)),
        clock=fixed_clock,
    )
    timeline = compile_c_project(pid, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    assert len(timeline.scenes) == n_scenes
    assert 30.0 <= timeline.total_duration_sec <= 60.0

    initialize_d_image_manifest(pid, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    confirm_d_image_manifest(
        pid, ready_d_payload(timeline), db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    script = generate_e_script(
        pid,
        db_path=db_path,
        projects_root=projects_root,
        provider=DevFakeEProvider(),
        clock=fixed_clock,
    )
    assert len(script.narration_script) == n_scenes

    manifest = generate_f_kdenlive_project(
        pid, db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    assert _status(db_path, pid) == "script_generated"
    assert manifest.canvas_width == 1080
    assert manifest.canvas_height == 1920
    assert manifest.fps == 30

    project_dir = projects_root / pid

    # Every timeline media resource exists on disk (no missing media).
    for scene in timeline.scenes:
        assert (project_dir / scene.image_path).is_file()
        assert (project_dir / scene.text_overlay_path).is_file()

    # project.kdenlive parses and declares the vertical 1080x1920 30fps profile.
    tree = ET.parse(project_dir / "project.kdenlive")
    root = tree.getroot()
    assert root.tag == "mlt"
    profile = root.find("profile")
    assert profile is not None
    assert profile.attrib["width"] == "1080"
    assert profile.attrib["height"] == "1920"
    assert profile.attrib["frame_rate_num"] == "30"
    assert profile.attrib["frame_rate_den"] == "1"

    # Every producer resource referenced by the XML exists (no missing media).
    for producer in root.findall("producer"):
        for prop in producer.findall("property"):
            if prop.attrib.get("name") == "resource":
                assert (project_dir / (prop.text or "")).is_file()


def _fractional_b_payload() -> dict:
    # Durations chosen so independent round(start*30)/round(dur*30) would create
    # off-by-one frame gaps/overlaps; the F builder must tile them contiguously.
    durs = [8.35, 8.35, 8.35, 8.35]
    scenes = []
    for i, per in enumerate(durs, start=1):
        purpose = "hook" if i == 1 else ("payoff" if i == len(durs) else "context")
        scenes.append(
            {
                "scene_id": f"s{i:02d}",
                "duration_sec": per,
                "purpose": purpose,
                "screen_text": f"Point {i}",
                "visual_direction": f"Neutral composition for scene {i}.",
                "image_slot_description": f"Neutral abstract image for scene {i}.",
                "narration_intent": f"Explain scene {i} from safe metadata only.",
                "source_basis": [f"fictional summary point {i}"],
                "do_not_say": [f"{SAFETY_GUARD_TERMS[0]} 추정 금지", f"{SAFETY_GUARD_TERMS[3]} 금지"],
            }
        )
    return {
        "schema_version": "b_scene_plan.v2.1",
        "selected_style": STYLES[0],
        "style_reason": "A concise structure fits this fictional sample.",
        "target_duration_sec": round(sum(durs)),
        "scene_plan": scenes,
        "risk_flags": ["identity inference prohibited", "direct quotation prohibited"],
    }


def test_fractional_durations_produce_contiguous_f_frames(tmp_path) -> None:
    db_path = tmp_path / "shorts.sqlite3"
    projects_root = tmp_path / "projects"
    project = create_project_from_candidate(
        make_candidate(0), db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    pid = project.project_id
    generate_b_scene_plan(
        pid, db_path=db_path, projects_root=projects_root,
        provider=VariedBProvider(_fractional_b_payload()), clock=fixed_clock,
    )
    timeline = compile_c_project(pid, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    initialize_d_image_manifest(pid, db_path=db_path, projects_root=projects_root, clock=fixed_clock)
    confirm_d_image_manifest(
        pid, ready_d_payload(timeline), db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )
    generate_e_script(
        pid, db_path=db_path, projects_root=projects_root, provider=DevFakeEProvider(), clock=fixed_clock
    )
    manifest = generate_f_kdenlive_project(
        pid, db_path=db_path, projects_root=projects_root, clock=fixed_clock
    )

    frames = manifest.scenes
    # Frames tile exactly: each scene ends where the next begins, no gaps/overlaps.
    for i in range(len(frames) - 1):
        assert frames[i].start_frame + frames[i].duration_frames == frames[i + 1].start_frame
    # The last scene runs to total_frames and every duration is positive.
    assert frames[-1].start_frame + frames[-1].duration_frames == manifest.total_frames
    assert all(scene.duration_frames > 0 for scene in frames)
    assert sum(scene.duration_frames for scene in frames) == manifest.total_frames

from __future__ import annotations

from shorts_pipeline.projectgen.timeline import assign_start_times


def test_assign_start_times_accumulates_duration_and_rounds() -> None:
    scenes = [
        {"scene_id": "s01", "duration_sec": 1.2349},
        {"scene_id": "s02", "duration_sec": 2.3451},
        {"scene_id": "s03", "duration_sec": 3.0},
    ]
    timed = assign_start_times(scenes)
    assert [scene["start_sec"] for scene in timed] == [0.0, 1.235, 3.58]


def test_assign_start_times_preserves_scene_id_order() -> None:
    scenes = [
        {"scene_id": "s01", "duration_sec": 2},
        {"scene_id": "s02", "duration_sec": 2},
    ]
    timed = assign_start_times(scenes)
    assert [scene["scene_id"] for scene in timed] == ["s01", "s02"]

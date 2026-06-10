"""Headless Streamlit smoke test driving app.py through the full A->F flow.

Uses Streamlit's ``AppTest`` to actually execute the rendering layer (not just
the controller), catching runtime errors in the UI itself. A fresh ``AppTest``
is used per stage so that disappearing form widgets do not trip AppTest's
cross-run widget-state bookkeeping; project state persists on disk and in
``session_state['project_id']`` between stages.

The whole module is skipped when the optional ``ui`` extra (Streamlit) is not
installed, so CI stays offline. No network egress occurs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import shorts_pipeline.ui.controller as ctrl  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parents[1] / "src" / "shorts_pipeline" / "ui" / "app.py")


def _fresh(base_dir, project_id: str | None = None) -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=90)
    at.session_state["base_dir"] = str(base_dir)
    if project_id is not None:
        at.session_state["project_id"] = project_id
    at.run()
    return at


def _click(at: AppTest, label_substring: str) -> AppTest:
    for button in at.button:
        if label_substring in button.label:
            button.click()
            at.run()
            return at
    raise AssertionError(
        f"button containing {label_substring!r} not found; have {[b.label for b in at.button]}"
    )


def test_ui_app_drives_full_a_to_f(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)

    # A: create a project from the candidate form (defaults are valid).
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    assert not at.exception
    project_id = at.session_state["project_id"]
    assert ctrl.current_status(cfg, project_id) == "candidate_selected"

    # B -> C: stage buttons.
    at = _click(_fresh(tmp_path, project_id), "장면 계획 생성")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "planned"

    at = _click(_fresh(tmp_path, project_id), "타임라인·에셋 컴파일")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "project_generated"

    # D: confirm the rights form (defaults keep all slots replaced + confirmed).
    at = _click(_fresh(tmp_path, project_id), "D 확인")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "images_inserted"

    # E -> F.
    at = _click(_fresh(tmp_path, project_id), "내레이션·제목 생성")
    assert not at.exception
    assert ctrl.current_status(cfg, project_id) == "script_generated"

    at = _click(_fresh(tmp_path, project_id), "Kdenlive 골격 생성")
    assert not at.exception

    project_dir = cfg.projects_root / project_id
    assert (project_dir / "project.kdenlive").is_file()
    assert (project_dir / "f_kdenlive_manifest.json").is_file()

    # The F result screen shows the local handoff paths.
    at_final = _fresh(tmp_path, project_id)
    shown = " ".join(block.value for block in at_final.code)
    assert "project.kdenlive" in shown


# --- Error-path coverage (W3) ----------------------------------------------


def _raise(*_args, **_kwargs):
    raise RuntimeError("forced failure")


def test_ui_unknown_project_renders_info_without_crash(tmp_path) -> None:
    at = _fresh(tmp_path, project_id="PRJ_20260101_9999")
    assert not at.exception
    # No status -> the app shows an informational message, not a crash.
    assert any("작업이 없습니다" in block.value for block in at.info)


def test_ui_create_failure_renders_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ctrl, "create_project", _raise)
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    assert not at.exception
    assert any("생성 실패" in block.value for block in at.error)


def test_ui_stage_failure_renders_error(tmp_path, monkeypatch) -> None:
    # Create a real project first, then force the B stage to fail.
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    project_id = at.session_state["project_id"]
    monkeypatch.setattr(ctrl, "run_b", _raise)
    at = _click(_fresh(tmp_path, project_id), "장면 계획 생성")
    assert not at.exception
    assert any("실패" in block.value for block in at.error)


# --- U1: one-click full draft + provider readiness panel -------------------


def test_ui_one_click_full_draft_reaches_f(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _click(_fresh(tmp_path), "전체 초안 생성 (A→F)")
    assert not at.exception
    project_id = at.session_state["project_id"]
    assert ctrl.current_status(cfg, project_id) == "script_generated"
    assert (cfg.projects_root / project_id / "project.kdenlive").is_file()


def test_ui_previews_render_after_full_draft(tmp_path) -> None:
    # One-click to F, then a fresh render shows the B/E previews.
    at = _click(_fresh(tmp_path), "전체 초안 생성 (A→F)")
    project_id = at.session_state["project_id"]

    at = _fresh(tmp_path, project_id)
    assert not at.exception
    markdown = " ".join(block.value for block in at.markdown)
    assert "s01" in markdown  # B scene plan preview
    assert any("추천 제목" in block.value for block in at.success)  # E preview


def _candidate(n: int) -> dict:
    return {
        "candidate_id": f"ui-{n}",
        "title": f"Safe fictional title {n}",
        "source_url": f"https://example.com/community/post/{n}",
        "community": "manual",
        "collected_at": "2026-06-01T09:00:00+09:00",
        "summary": "A neutral fictional summary.",
        "hook": "A neutral hook.",
        "why_shortable": "A neutral rationale.",
        "risk_flags_for_user": [],
        "status": "selected",
    }


def test_ui_lists_and_resumes_projects(tmp_path) -> None:
    from datetime import datetime

    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    first = ctrl.create_project(cfg, _candidate(1), clock=lambda: datetime(2026, 6, 4, 9))
    second = ctrl.create_project(cfg, _candidate(2), clock=lambda: datetime(2026, 6, 4, 10))

    at = _fresh(tmp_path)
    labels = [button.label for button in at.button]
    assert any(first.project_id in label for label in labels)
    assert any(second.project_id in label for label in labels)

    at = _click(_fresh(tmp_path), f"{first.project_id} 열기")
    assert not at.exception
    assert at.session_state["project_id"] == first.project_id


def test_ui_regenerate_creates_new_project(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _click(_fresh(tmp_path), "전체 초안 생성 (A→F)")
    original = at.session_state["project_id"]

    at = _click(_fresh(tmp_path, original), "새 초안으로 재생성")
    assert not at.exception
    new_id = at.session_state["project_id"]
    assert new_id != original
    assert ctrl.current_status(cfg, new_id) == "script_generated"


def test_ui_edit_candidate_returns_to_prefilled_form(tmp_path) -> None:
    at = _click(_fresh(tmp_path), "전체 초안 생성 (A→F)")
    pid = at.session_state["project_id"]

    at = _click(_fresh(tmp_path, pid), "후보 편집 후 다시 시작")
    assert not at.exception
    assert "project_id" not in at.session_state
    assert at.session_state["edit_candidate"]["title"]  # candidate stashed for editing


def test_ui_first_run_help_and_stage_hint(tmp_path) -> None:
    # First run (no projects): the how-it-works help is shown.
    at = _fresh(tmp_path)
    assert not at.exception
    help_text = " ".join(block.value for block in at.markdown)
    assert "Kdenlive에서 마무리" in help_text

    # After creating a project, a per-stage "다음:" hint appears.
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    project_id = at.session_state["project_id"]
    at = _fresh(tmp_path, project_id)
    assert not at.exception
    assert any("다음:" in block.value for block in at.info)


def test_ui_wizard_discovers_then_drafts_to_f(tmp_path, monkeypatch) -> None:
    from shorts_pipeline.sources import DiscoveredCandidate

    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    fake = [
        DiscoveredCandidate(
            title="화제 후보 1", url="https://example.com/1", source="rss", excerpt="요약 발췌"
        )
    ]
    monkeypatch.setattr(ctrl, "discover_candidates", lambda kind, query="": fake)

    at = _fresh(tmp_path)
    at.selectbox[0].set_value("RSS 피드 (루리웹·인벤·임의 피드)").run()
    at = _click(at, "지금 가져오기")
    assert not at.exception

    # The draft-edit form is pre-filled; edit the title, then generate.
    at.text_input[1].set_value("내가 고친 제목")
    at = _click(at, "이 내용으로 전체 초안 생성")
    assert not at.exception
    project_id = at.session_state["project_id"]
    assert ctrl.current_status(cfg, project_id) == "script_generated"
    assert ctrl.load_candidate(cfg, project_id)["title"] == "내가 고친 제목"


def test_ui_handoff_screen_shows_checklist_and_downloads(tmp_path) -> None:
    at = _click(_fresh(tmp_path), "전체 초안 생성 (A→F)")
    project_id = at.session_state["project_id"]

    at = _fresh(tmp_path, project_id)
    assert not at.exception  # download widgets render without crashing
    headings = " ".join(block.value for block in at.subheader)
    markdown = " ".join(block.value for block in at.markdown)
    assert "다음 할 일" in headings or "다음 할 일" in markdown
    code = " ".join(block.value for block in at.code)
    assert "project.kdenlive" in code


def test_ui_paste_mode_analyzes_and_creates_project(tmp_path) -> None:
    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _fresh(tmp_path)  # default source is "내용 붙여넣기"
    at.text_area[0].set_value("디시 실베 화제 제목\n핵심 요약 내용입니다.").run()
    at = _click(at, "분석하기")
    assert not at.exception

    at = _click(at, "프로젝트 만들기")  # Claude Code 단계별
    assert not at.exception
    pid = at.session_state["project_id"]
    assert ctrl.current_status(cfg, pid) == "candidate_selected"
    assert ctrl.load_candidate(cfg, pid)["title"] == "디시 실베 화제 제목"


def test_ui_paste_mode_empty_shows_error(tmp_path) -> None:
    at = _fresh(tmp_path)
    at.text_area[0].set_value("   ").run()
    at = _click(at, "분석하기")
    assert not at.exception
    assert any("분석 실패" in block.value for block in at.error)


def test_ui_wizard_empty_result_shows_message(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ctrl, "discover_candidates", lambda kind, query="": [])
    at = _fresh(tmp_path)
    at.selectbox[0].set_value("RSS 피드 (루리웹·인벤·임의 피드)").run()
    at = _click(at, "지금 가져오기")
    assert not at.exception
    assert any("결과가 없습니다" in block.value for block in at.info)


def test_ui_wizard_fetch_failure_shows_friendly_error(tmp_path, monkeypatch) -> None:
    from shorts_pipeline.sources import SourceError

    def _boom(kind, query=""):
        raise SourceError("네트워크 요청 실패")

    monkeypatch.setattr(ctrl, "discover_candidates", _boom)
    at = _fresh(tmp_path)
    at.selectbox[0].set_value("RSS 피드 (루리웹·인벤·임의 피드)").run()
    at = _click(at, "지금 가져오기")
    assert not at.exception
    assert any("가져오기 실패" in block.value for block in at.error)


def test_ui_dummy_mode_notice_points_to_paste_bridge(tmp_path, monkeypatch) -> None:
    for name in (
        "SHORTS_PIPELINE_ENABLE_REAL_LLM",
        "SHORTS_PIPELINE_LLM_BACKEND",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    pid = at.session_state["project_id"]
    at = _fresh(tmp_path, pid)
    assert not at.exception
    info = " ".join(block.value for block in at.info)
    assert "더미" in info and "Claude Code" in info


def test_ui_dummy_notice_absent_after_paste_applied(tmp_path) -> None:
    # After real content is pasted for B, the C-stage screen must NOT claim the
    # titles/narration are dummy examples (the old global banner was misleading).
    import json as _json

    from shorts_pipeline.dev_fakes import DevFakeBProvider
    from shorts_pipeline.models import SourceArtifact

    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    pid = at.session_state["project_id"]
    source = SourceArtifact.model_validate_json(
        (cfg.projects_root / pid / "source.json").read_text(encoding="utf-8")
    )
    b_json = _json.dumps(
        DevFakeBProvider().generate(source=source, prompt_version="v", previous_errors=[])
    )
    at = _fresh(tmp_path, pid)
    at.text_area[0].set_value(b_json).run()
    at = _click(at, "적용")

    at = _fresh(tmp_path, pid)  # now at the C stage
    assert not at.exception
    infos = " ".join(block.value for block in at.info)
    assert "예시 출력" not in infos and "더미(예시) 모드" not in infos


def test_ui_paste_bridge_b_applies_to_planned(tmp_path) -> None:
    import json as _json

    from shorts_pipeline.dev_fakes import DevFakeBProvider
    from shorts_pipeline.models import SourceArtifact

    cfg = ctrl.PipelineConfig.from_base_dir(tmp_path)
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    pid = at.session_state["project_id"]

    source = SourceArtifact.model_validate_json(
        (cfg.projects_root / pid / "source.json").read_text(encoding="utf-8")
    )
    b_json = _json.dumps(
        DevFakeBProvider().generate(source=source, prompt_version="v", previous_errors=[])
    )

    at = _fresh(tmp_path, pid)
    at.text_area[0].set_value(b_json).run()
    at = _click(at, "적용")
    assert not at.exception
    assert ctrl.current_status(cfg, pid) == "planned"


def test_ui_paste_bridge_shows_tone_and_playbook(tmp_path) -> None:
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    pid = at.session_state["project_id"]
    at = _fresh(tmp_path, pid)
    assert not at.exception
    # tone selector present (default 자극적) and the prompt carries the playbook + tone
    assert any("자극적" in opt for sb in at.selectbox for opt in sb.options)
    code = " ".join(block.value for block in at.code)
    assert "톤=자극적" in code and "훅" in code


def test_ui_paste_bridge_community_tone_reflects_in_prompt(tmp_path) -> None:
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    pid = at.session_state["project_id"]
    at = _fresh(tmp_path, pid)
    # the community tone is offered in the selector
    assert any("커뮤니티" in opt for sb in at.selectbox for opt in sb.options)
    # selecting it re-parameterizes the exported prompt
    at.selectbox[0].set_value("커뮤니티(반말·밈)").run()
    assert not at.exception
    code = " ".join(block.value for block in at.code)
    assert "반말" in code and "비속어" in code


def test_ui_paste_bridge_invalid_paste_shows_error(tmp_path) -> None:
    at = _click(_fresh(tmp_path), "프로젝트 생성")
    pid = at.session_state["project_id"]

    at = _fresh(tmp_path, pid)
    at.text_area[0].set_value("이건 JSON이 아니에요 {{{").run()
    at = _click(at, "적용")
    assert not at.exception
    assert any("적용 실패" in block.value for block in at.error)


def test_ui_wizard_gates_unconfigured_source(tmp_path, monkeypatch) -> None:
    for name in ("YOUTUBE_API_KEY", "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    at = _fresh(tmp_path)
    # Select the YouTube source, which needs a key that is not set.
    at.selectbox[0].set_value("YouTube 인기영상 (KR)").run()
    assert not at.exception
    text = " ".join(block.value for block in (*at.warning, *at.markdown))
    assert "YOUTUBE_API_KEY" in text
    fetch = next(button for button in at.button if "지금 가져오기" in button.label)
    assert fetch.disabled is True


def test_ui_provider_panel_shows_enable_guidance(tmp_path, monkeypatch) -> None:
    for name in (
        "SHORTS_PIPELINE_ENABLE_REAL_LLM",
        "SHORTS_PIPELINE_LLM_BACKEND",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    at = _fresh(tmp_path)
    assert not at.exception
    guidance = " ".join(block.value for block in at.info)
    assert "SHORTS_PIPELINE_ENABLE_REAL_LLM" in guidance

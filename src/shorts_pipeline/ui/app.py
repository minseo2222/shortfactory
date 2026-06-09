"""쇼츠 파이프라인 로컬 Streamlit UI (화제 발굴 → A~F 초안).

실행:

    python -m streamlit run src/shorts_pipeline/ui/app.py

이 파일은 얇은 렌더링 레이어이며 오케스트레이션은 모두 ``controller.py``에 있습니다.
네트워크 전송은 사용자가 명시적으로 누를 때(소스 가져오기/opt-in 실제 LLM)만 일어납니다.
영상 렌더·TTS·업로드·외부 `.kdenlive` 신뢰는 하지 않습니다.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from shorts_pipeline.config import load_local_env
from shorts_pipeline.security import ensure_relative_project_path
from shorts_pipeline.ui import controller as ctrl

DEFAULT_BASE_DIR = str(Path(".local").resolve())


def _config() -> ctrl.PipelineConfig:
    base_dir = st.session_state.get("base_dir", DEFAULT_BASE_DIR)
    return ctrl.PipelineConfig.from_base_dir(base_dir)


# 알려진 예외를 평범한 한국어 다음 단계 안내로 매핑(비밀·스택트레이스 노출 없음).
_ERROR_HINTS = {
    "MissingApiKeyError": "환경변수에 제공자 API 키를 설정하세요(사이드바 패널 참고).",
    "MissingSdkError": '선택 LLM 확장을 설치하세요: pip install -e ".[llm]".',
    "LlmTransientError": "제공자 일시 오류입니다. 잠시 후 다시 시도하세요.",
    "LlmResponseError": "모델 응답이 예상과 달랐습니다. 재생성을 시도하세요.",
    "OutboundContentError": "외부 전송 안전 점검에 막혔습니다. 요약/훅을 수정하세요.",
    "UserImageError": "이미지가 거부됐습니다. 형식과 크기 제한을 확인하세요.",
    "ProjectStatusError": "현재 프로젝트 상태에서는 할 수 없는 작업입니다.",
    "ValidationError": "생성 내용 검증에 실패했습니다. 재생성을 시도하세요.",
    "SourceError": "소스를 가져오지 못했습니다. 키/URL을 확인하거나 다른 소스를 시도하세요.",
}

# 현재 상태별로 "이 단계가 무엇을 하는지 / 다음에 할 일".
_STAGE_HINTS = {
    "candidate_selected": "B: 요약을 바탕으로 LLM이 장면별 계획을 만듭니다.",
    "planned": "C: 타임라인과 플레이스홀더 PNG 에셋을 생성합니다.",
    "project_generated": "D: 권리처리된 이미지를 넣거나(또는 플레이스홀더 유지) 확인합니다.",
    "waiting_for_user_images": "D: 권리처리된 이미지를 넣고 권리를 확인합니다.",
    "images_inserted": "E: LLM이 내레이션과 제목 후보를 작성합니다.",
    "script_generated": "F: 열어서 편집을 마무리할 로컬 Kdenlive 프로젝트를 만듭니다.",
}


def _friendly_error(exc: Exception) -> str:
    hint = _ERROR_HINTS.get(type(exc).__name__)
    return f"{exc}" if hint is None else f"{exc}\n\n{hint}"


def _provider_panel() -> None:
    """비밀값 없는 실제 LLM 준비상태 패널(이름만, 값 미표시)."""
    info = ctrl.readiness()
    st.sidebar.write(f"AI 제공자 모드: `{info['mode']}`")
    if info["ready"]:
        st.sidebar.success(f"실제 LLM 준비됨: {info['backend']}")
        return
    if info["real_enabled"] and not info["key_present"]:
        st.sidebar.warning("실제 LLM이 선택됐지만 설정이 완전하지 않습니다. 호출이 실패합니다.")
    else:
        st.sidebar.caption("설정 전까지는 결정적 더미(오프라인)를 사용합니다.")
    lines = ["실제 LLM을 켜려면 아래를 설정하세요(값은 표시되지 않습니다):"]
    lines += [f"- {item}" for item in info["missing"]]
    st.sidebar.info("\n".join(lines))


def _sidebar() -> None:
    st.sidebar.header("세션")
    st.session_state.setdefault("base_dir", DEFAULT_BASE_DIR)
    st.session_state["base_dir"] = st.sidebar.text_input(
        "로컬 작업 폴더", value=st.session_state["base_dir"]
    )
    _provider_panel()
    project_id = st.session_state.get("project_id")
    if project_id:
        st.sidebar.write(f"프로젝트: `{project_id}`")
        status = ctrl.current_status(_config(), project_id)
        st.sidebar.write(f"상태: `{status}`")
        st.sidebar.subheader("상태 기록")
        for event in ctrl.status_events(_config(), project_id):
            st.sidebar.write(f"{event.from_status or '-'} -> {event.to_status} ({event.stage})")

    _project_picker(project_id)


def _project_picker(current_id: str | None) -> None:
    projects = ctrl.list_projects(_config())
    if projects:
        st.sidebar.subheader("프로젝트 열기")
        for summary in projects:
            marker = "* " if summary.project_id == current_id else ""
            label = f"{marker}{summary.project_id} 열기 [{summary.status}]"
            if st.sidebar.button(label, key=f"open_{summary.project_id}"):
                st.session_state["project_id"] = summary.project_id
                st.rerun()
    if st.sidebar.button("새 프로젝트"):
        st.session_state.pop("project_id", None)
        st.rerun()


def _first_run_help() -> None:
    if ctrl.list_projects(_config()):
        return  # 재방문 사용자에게는 숨김
    with st.expander("사용법 (먼저 읽기)", expanded=True):
        st.markdown(
            "1. **화제 가져오기** — 공식 API/공개 RSS/내가 고른 링크로 후보를 모읍니다.\n"
            "2. **후보 선택** — 마음에 드는 항목을 하나 고릅니다.\n"
            "3. **초안 생성(A→F)** — 요약·훅을 자동 초안하고 LLM이 장면·내레이션을 만듭니다.\n"
            "4. **이미지·마무리** — 권리처리 이미지를 넣고 Kdenlive에서 마무리합니다.\n\n"
            "자동 크롤링·우회·렌더·TTS·업로드는 하지 않습니다 — 마지막은 Kdenlive에서 마무리합니다."
        )


def _candidate_form() -> None:
    st.subheader("A. 직접 입력")
    st.caption(
        "직접 요약/훅을 채운 뒤, 단계별로 진행하거나 한 번에 전체 초안(A→F)을 만들 수 있습니다. "
        "원클릭은 플레이스홀더 이미지를 쓰며, 최종 편집 전에 교체하면 됩니다."
    )
    prefill = st.session_state.get("edit_candidate", {})
    if prefill:
        st.info("기존 후보의 사본을 편집 중입니다. 제출하면 새 프로젝트가 생성됩니다.")
    with st.form("candidate"):
        source_url = st.text_input(
            "출처 URL", value=prefill.get("source_url", "https://example.com/community/post/1")
        )
        community = st.text_input("커뮤니티", value=prefill.get("community", "manual"))
        title = st.text_input("출처 제목", value=prefill.get("title", "안전한 가상의 출처 제목"))
        summary = st.text_area("요약(직접 작성)", value=prefill.get("summary", "중립적인 가상 요약."))
        hook = st.text_input("훅", value=prefill.get("hook", "중립적인 훅."))
        why = st.text_input("숏폼 적합 이유", value=prefill.get("why_shortable", "중립적인 근거."))
        col_a, col_b = st.columns(2)
        created = col_a.form_submit_button("프로젝트 생성 (A)")
        full_draft = col_b.form_submit_button("전체 초안 생성 (A→F)")
    if not (created or full_draft):
        return
    candidate = {
        "candidate_id": "ui-candidate",
        "title": title,
        "source_url": source_url,
        "community": community,
        "collected_at": "2026-06-01T09:00:00+09:00",
        "summary": summary,
        "hook": hook,
        "why_shortable": why,
        "risk_flags_for_user": [],
        "status": "selected",
    }
    try:
        if full_draft:
            with st.spinner("전체 초안 생성 중 (렌더·업로드 없음)..."):
                result = ctrl.run_full_pipeline(_config(), candidate)
            st.session_state["project_id"] = result["project_id"]
            st.success(f"전체 초안 완료: {result['project_id']} ({result['status']})")
        else:
            project = ctrl.create_project(_config(), candidate)
            st.session_state["project_id"] = project.project_id
            st.success(f"생성됨: {project.project_id}")
        st.session_state.pop("edit_candidate", None)
        st.rerun()
    except Exception as exc:  # 사용자에게 그대로 노출, 삼키지 않음
        action = "전체 초안 실패" if full_draft else "생성 실패"
        st.error(f"{action}: {_friendly_error(exc)}")


def _stage_button(label: str, action) -> None:
    if st.button(label):
        try:
            action()
            st.rerun()
        except Exception as exc:
            st.error(f"{label} 실패: {_friendly_error(exc)}")


def _paste_bridge(project_id: str, stage: str) -> None:
    """No-API path: copy a prompt into Claude Code/Codex, paste the JSON back."""
    config = _config()
    title = "장면 계획 (B)" if stage == "b" else "내레이션·제목 (E)"
    build_prompt = ctrl.b_paste_prompt if stage == "b" else ctrl.e_paste_prompt
    apply = ctrl.apply_pasted_b if stage == "b" else ctrl.apply_pasted_e
    with st.expander(f"🟦 Claude Code/Codex로 생성 (API 키 불필요) — {title}", expanded=True):
        tone = st.selectbox(
            "톤(자극 강도)", ctrl.shorts_tones(), key=f"tone_{stage}_{project_id}"
        )
        try:
            prompt = build_prompt(config, project_id, None, tone)
        except Exception as exc:
            st.warning(f"프롬프트를 만들 수 없습니다: {_friendly_error(exc)}")
            return
        st.caption(
            "① 톤을 고르고 → ② 아래 프롬프트를 복사해 Claude Code/Codex에 붙여넣고 → ③ 받은 "
            "JSON을 아래 칸에 붙여넣은 뒤 → ④ 적용을 누르세요. (네트워크·API 키를 쓰지 않습니다.)"
        )
        st.code(prompt)
        pasted = st.text_area(
            "받은 JSON 붙여넣기", key=f"paste_{stage}_{project_id}", height=160
        )
        if st.button("적용", key=f"apply_{stage}_{project_id}"):
            try:
                apply(config, project_id, pasted)
                st.success("적용되었습니다.")
                st.rerun()
            except Exception as exc:
                st.error(f"적용 실패: {_friendly_error(exc)}")
                try:
                    retry = build_prompt(config, project_id, [str(exc)], tone)
                    st.caption("아래 재시도 프롬프트(오류 포함)를 다시 붙여넣어 보세요:")
                    st.code(retry)
                except Exception:
                    pass


def _d_form(project_id: str) -> None:
    st.subheader("D. 이미지 삽입·권리 확인")
    st.write(
        "장면별로 권리처리된 이미지를 업로드하세요(선택 — 생성된 플레이스홀더로도 시험 가능). "
        "그런 다음 아래에서 권리를 확인합니다."
    )
    config = _config()
    timeline = ctrl.load_timeline(config, project_id)
    if timeline is None:
        st.warning("타임라인이 없습니다. 먼저 C를 실행하세요.")
        return
    project_dir = config.projects_root / project_id

    # 업로더는 폼 밖에 두어 업로드 즉시 미리보기·저장되게 합니다.
    for scene in timeline.scenes:
        uploaded = st.file_uploader(
            f"{scene.scene_id} 이미지",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"upload_{scene.scene_id}",
        )
        if uploaded is not None:
            try:
                ctrl.store_user_image(
                    config, project_id, scene.image_path, uploaded.getvalue(),
                    filename=uploaded.name,
                )
                st.caption(f"`{uploaded.name}` → `{scene.image_path}` 저장됨")
            except Exception as exc:
                st.error(f"{scene.scene_id} 이미지 거부됨: {_friendly_error(exc)}")
        abs_path = project_dir / ensure_relative_project_path(scene.image_path)
        if abs_path.is_file():
            st.image(str(abs_path), width=160, caption=scene.scene_id)

    with st.form("d_confirm"):
        all_rights = st.checkbox(
            "모든 이미지의 권리를 보유함을 확인합니다", value=True, key="d_all_rights"
        )
        no_capture = st.checkbox(
            "원본 출처의 스크린샷/캡처가 아닙니다",
            value=True,
            key="d_no_capture",
        )
        submitted = st.form_submit_button("D 확인")
    if submitted:
        try:
            if ctrl.current_status(config, project_id) == "project_generated":
                ctrl.init_d(config, project_id)
            slot_inputs = {
                scene.scene_id: {
                    "rights_confirmed_by_user": all_rights,
                    "contains_original_capture": not no_capture,
                }
                for scene in timeline.scenes
            }
            payload = ctrl.build_ready_d_payload(timeline, slot_inputs=slot_inputs)
            ctrl.confirm_d(config, project_id, payload)
            st.success("D 확인됨")
            st.rerun()
        except Exception as exc:
            st.error(f"D 확인 실패: {_friendly_error(exc)}")


def _preview_b(plan) -> None:
    st.subheader("장면 계획 (B)")
    st.caption(f"{len(plan.scene_plan)}개 장면 · 목표 {plan.target_duration_sec}초")
    for scene in plan.scene_plan:
        st.markdown(f"- `{scene.scene_id}` · {scene.duration_sec:g}초 · {scene.screen_text}")
        st.caption(scene.narration_intent)


def _preview_c_assets(project_id: str, timeline) -> None:
    st.subheader("생성된 에셋 (C)")
    project_dir = _config().projects_root / project_id
    shown = [
        scene
        for scene in timeline.scenes
        if (project_dir / ensure_relative_project_path(scene.image_path)).is_file()
    ]
    if not shown:
        st.caption("아직 에셋 이미지가 없습니다.")
        return
    columns = st.columns(min(3, len(shown)))
    for index, scene in enumerate(shown):
        abs_path = project_dir / ensure_relative_project_path(scene.image_path)
        columns[index % len(columns)].image(str(abs_path), caption=scene.scene_id)


def _preview_e(script) -> None:
    st.subheader("내레이션·제목 (E)")
    st.success(f"추천 제목: {script.recommended_title}")
    st.markdown("**제목 후보**")
    for candidate in script.title_candidates:
        st.markdown(f"- {candidate.title} _({candidate.angle})_")
    st.markdown("**내레이션**")
    for line in script.narration_script:
        st.markdown(f"- `{line.scene_id}` ({line.pace}): {line.script}")


def _render_previews(project_id: str) -> None:
    """디스크에 존재하는 단계 산출물의 읽기전용 미리보기."""
    config = _config()
    try:
        plan = ctrl.load_b_plan(config, project_id)
        if plan is not None:
            _preview_b(plan)
        timeline = ctrl.load_timeline(config, project_id)
        if timeline is not None:
            _preview_c_assets(project_id, timeline)
        script = ctrl.load_e_script(config, project_id)
        if script is not None:
            _preview_e(script)
    except Exception as exc:  # 미리보기 오류가 앱 전체를 죽이면 안 됨
        st.warning(f"미리보기 불가: {exc}")


def _download_button(project_id: str, relative_name: str, label: str, mime: str) -> None:
    data = ctrl.read_project_file(_config(), project_id, relative_name)
    if data is None:
        return
    st.download_button(
        label,
        data=data,
        file_name=Path(relative_name).name,
        mime=mime,
        key=f"dl_{relative_name}",
    )


def _show_f_result(project_id: str) -> None:
    config = _config()
    project_dir = config.projects_root / project_id
    st.success("F: 초안이 완성됐습니다. Kdenlive에서 열어 마무리하세요.")

    st.subheader("다음 할 일")
    st.markdown(
        "1. 프로젝트 폴더에서 `assets/user_images/`의 플레이스홀더를 권리처리된 이미지로 교체\n"
        "2. `project.kdenlive`를 Kdenlive에서 열기\n"
        "3. 내레이션 녹음·자막·컷 편집으로 마무리 (이 도구는 렌더·업로드하지 않음)"
    )

    st.write("프로젝트 폴더:")
    st.code(str(project_dir))
    st.write("Kdenlive 프로젝트 파일:")
    st.code(str(project_dir / "project.kdenlive"))

    _download_button(
        project_id, "project.kdenlive", "project.kdenlive 다운로드", "application/xml"
    )
    _download_button(
        project_id,
        "notes/manual_kdenlive_editing.md",
        "핸드오프 노트 다운로드",
        "text/markdown",
    )


def _regenerate_actions(project_id: str) -> None:
    config = _config()
    st.divider()
    st.caption(
        "초안이 마음에 안 드나요? 재생성은 같은 후보로 새 프로젝트를 만듭니다(실제 LLM이면 다른 결과). "
        "편집은 후보를 먼저 수정합니다. 제자리 단계 재실행은 의도적으로 제공하지 않습니다."
    )
    col_a, col_b = st.columns(2)
    if col_a.button("새 초안으로 재생성 (A→F)"):
        try:
            with st.spinner("새 초안 재생성 중..."):
                new_id = ctrl.regenerate_draft(config, project_id)
            st.session_state["project_id"] = new_id
            st.success(f"새 초안: {new_id}")
            st.rerun()
        except Exception as exc:
            st.error(f"재생성 실패: {_friendly_error(exc)}")
    if col_b.button("후보 편집 후 다시 시작"):
        candidate = ctrl.load_candidate(config, project_id)
        if candidate is None:
            st.error("편집할 저장된 후보가 없습니다.")
        else:
            st.session_state["edit_candidate"] = candidate
            st.session_state.pop("project_id", None)
            st.rerun()


_SOURCE_CHOICES = {
    "내용 붙여넣기 (디시·루리웹 등 복사한 글)": ("paste", "", ""),
    "RSS 피드 (루리웹·인벤·임의 피드)": ("rss", "RSS 피드 URL", "https://bbs.ruliweb.com/news/rss"),
    "링크 1개 (공개 글 주소)": ("link", "공개 글 링크 1개", ""),
    "YouTube 인기영상 (KR)": ("youtube", "", ""),
    "네이버 검색 (키워드)": ("naver", "검색어", ""),
}


def _paste_source_input() -> None:
    st.caption(
        "디시 실베·루리웹 등에서 읽은 글을 복사해 붙여넣으세요. 네트워크 호출 없이 로컬에서 "
        "분석합니다(원문은 저장하지 않고 요약만 보관)."
    )
    pasted_text = st.text_area("복사한 글 내용", key="paste_content", height=200)
    pasted_url = st.text_input("출처 URL (선택)", value="", key="paste_url")
    if st.button("분석하기"):
        try:
            cand = ctrl.analyze_pasted_content(pasted_text, pasted_url)
            st.session_state["discovered"] = [cand.model_dump()]
        except Exception as exc:
            st.session_state.pop("discovered", None)
            st.error(f"분석 실패: {_friendly_error(exc)}")


def _fetch_source_input(kind: str, query_label: str, default: str) -> None:
    readiness = ctrl.source_readiness().get(kind, {"ready": True, "needs": []})
    if not readiness["ready"]:
        st.warning(
            "이 소스는 키 설정이 필요합니다 — 환경변수 "
            + ", ".join(readiness["needs"])
            + " 를 설정하세요(값은 표시되지 않습니다)."
        )
    else:
        st.caption("바로 사용 가능합니다." if kind in {"rss", "link"} else "키가 설정되어 사용 가능합니다.")

    query = st.text_input(query_label, value=default, key="disc_query") if query_label else ""

    if st.button("지금 가져오기", disabled=not readiness["ready"]):
        try:
            with st.spinner("가져오는 중..."):
                found = ctrl.discover_candidates(kind, query)
            st.session_state["discovered"] = [c.model_dump() for c in found]
            if not found:
                st.info(
                    "결과가 없습니다. 다른 소스나 검색어를 시도하거나, 잠시 후 다시 시도해 보세요."
                )
        except Exception as exc:
            st.session_state.pop("discovered", None)
            st.error(f"가져오기 실패: {_friendly_error(exc)}")


def _discovery_wizard() -> None:
    st.subheader("1) 화제 가져오기")
    st.caption(
        "내가 복사한 글을 붙여넣거나, 공식 API·공개 RSS·링크로 가져옵니다. "
        "자동 크롤링·우회는 하지 않습니다."
    )
    label = st.selectbox("소스", list(_SOURCE_CHOICES.keys()), key="disc_kind")
    kind, query_label, default = _SOURCE_CHOICES[label]

    if kind == "paste":
        _paste_source_input()
    else:
        _fetch_source_input(kind, query_label, default)

    discovered = st.session_state.get("discovered") or []
    if not discovered:
        return

    st.subheader("2) 후보 선택")
    st.caption(f"{len(discovered)}개 후보를 찾았습니다. 하나를 고르세요.")
    options = list(range(len(discovered)))

    def _fmt(index: int) -> str:
        item = discovered[index]
        score = f" · 👍 {item['score']}" if item.get("score") else ""
        return f"[{item.get('source', '')}] {item['title']}{score}"

    picked = st.radio("후보", options, format_func=_fmt, key="disc_pick")
    chosen = discovered[picked]
    if chosen.get("excerpt"):
        st.caption(chosen["excerpt"])

    st.subheader("3) 초안 다듬기")
    st.caption(
        "자동 초안된 제목·요약·훅을 고친 뒤, Claude Code/Codex로 단계별 생성(권장, API 불필요) "
        "하거나 더미로 한 번에 만들 수 있습니다."
    )
    seed = ctrl.draft_fields_from_discovered(chosen)
    with st.form("draft_edit"):
        edited_title = st.text_input("제목", value=seed["title"], key=f"draft_title_{picked}")
        edited_summary = st.text_area("요약", value=seed["summary"], key=f"draft_summary_{picked}")
        edited_hook = st.text_input("훅", value=seed["hook"], key=f"draft_hook_{picked}")
        edited_why = st.text_input(
            "숏폼 적합 이유", value=seed["why_shortable"], key=f"draft_why_{picked}"
        )
        col_full, col_create = st.columns(2)
        submit_create = col_create.form_submit_button("프로젝트 만들기 (Claude Code 단계별)")
        submit_full = col_full.form_submit_button("이 내용으로 전체 초안 생성 (A→F, 더미)")
    if submit_full or submit_create:
        try:
            candidate = ctrl.candidate_from_fields(
                source_url=str(chosen.get("url") or ""),
                source=str(chosen.get("source") or ""),
                title=edited_title,
                summary=edited_summary,
                hook=edited_hook,
                why_shortable=edited_why,
            )
            if submit_full:
                with st.spinner("초안 생성 중 (렌더·업로드 없음)..."):
                    result = ctrl.run_full_pipeline(_config(), candidate)
                st.session_state["project_id"] = result["project_id"]
                st.success(f"초안 완료: {result['project_id']}")
            else:
                project = ctrl.create_project(_config(), candidate)
                st.session_state["project_id"] = project.project_id
                st.success(f"프로젝트 생성: {project.project_id} — 아래 단계에서 Claude Code로 생성하세요.")
            st.session_state.pop("discovered", None)
            st.rerun()
        except Exception as exc:
            st.error(f"초안 생성 실패: {_friendly_error(exc)}")


def main() -> None:
    load_local_env()
    st.set_page_config(page_title="쇼츠 파이프라인", layout="wide")
    st.title("쇼츠 파이프라인 — 화제 발굴부터 초안까지")
    _sidebar()

    project_id = st.session_state.get("project_id")
    if not project_id:
        _first_run_help()
        _discovery_wizard()
        with st.expander("직접 입력 (고급)"):
            _candidate_form()
        return

    config = _config()
    status = ctrl.current_status(config, project_id)
    st.write(f"현재 상태: `{status}`")
    if ctrl.readiness()["mode"] == "fake":
        st.info(
            "ℹ️ 더미(예시) 모드입니다 — 생성되는 제목·내레이션은 예시입니다. B/E 단계의 "
            "'Claude Code/Codex로 생성'에 프롬프트를 붙여넣으면 진짜 한국어 초안을 만들 수 있습니다(API 키 불필요)."
        )
    hint = _STAGE_HINTS.get(status or "")
    if hint:
        st.info(f"다음: {hint}")

    _render_previews(project_id)

    if status == "candidate_selected":
        _paste_bridge(project_id, "b")
        _stage_button("장면 계획 생성 (B, 더미)", lambda: ctrl.run_b(config, project_id))
    elif status == "planned":
        _stage_button("타임라인·에셋 컴파일 (C)", lambda: ctrl.run_c(config, project_id))
    elif status in {"project_generated", "waiting_for_user_images"}:
        _d_form(project_id)
    elif status == "images_inserted":
        _paste_bridge(project_id, "e")
        _stage_button("내레이션·제목 생성 (E, 더미)", lambda: ctrl.run_e(config, project_id))
    elif status == "script_generated":
        if (config.projects_root / project_id / "project.kdenlive").exists():
            _show_f_result(project_id)
        else:
            _stage_button("Kdenlive 골격 생성 (F)", lambda: ctrl.run_f(config, project_id))
    else:
        st.info(f"이 상태에서는 작업이 없습니다: `{status}`")

    _regenerate_actions(project_id)


if __name__ == "__main__":
    main()

"""Local single-user Streamlit UI for the Shorts Pipeline (A->F).

Run with:

    python -m streamlit run src/shorts_pipeline/ui/app.py

This file is a thin rendering layer. All orchestration lives in
``controller.py``. The UI never performs network egress: B/E use the
deterministic fake providers unless the explicit real-LLM opt-in is configured.
It does not render video, run TTS, upload, or trust external `.kdenlive` files.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from shorts_pipeline.config import load_local_env
from shorts_pipeline.ui import controller as ctrl

DEFAULT_BASE_DIR = str(Path(".local").resolve())


def _config() -> ctrl.PipelineConfig:
    base_dir = st.session_state.get("base_dir", DEFAULT_BASE_DIR)
    return ctrl.PipelineConfig.from_base_dir(base_dir)


def _sidebar() -> None:
    st.sidebar.header("Session")
    st.session_state.setdefault("base_dir", DEFAULT_BASE_DIR)
    st.session_state["base_dir"] = st.sidebar.text_input(
        "Local working directory", value=st.session_state["base_dir"]
    )
    st.sidebar.write(f"Provider mode: `{ctrl.provider_mode()}`")
    project_id = st.session_state.get("project_id")
    if project_id:
        st.sidebar.write(f"Project: `{project_id}`")
        status = ctrl.current_status(_config(), project_id)
        st.sidebar.write(f"Status: `{status}`")
        st.sidebar.subheader("Status history")
        for event in ctrl.status_events(_config(), project_id):
            st.sidebar.write(f"{event.from_status or '-'} -> {event.to_status} ({event.stage})")
    if st.sidebar.button("Reset session"):
        st.session_state.pop("project_id", None)
        st.rerun()


def _candidate_form() -> None:
    st.subheader("A. Manual candidate")
    with st.form("candidate"):
        source_url = st.text_input("Source URL", value="https://example.com/community/post/1")
        community = st.text_input("Community", value="manual")
        title = st.text_input("Source title", value="A safe fictional source title")
        summary = st.text_area("Your summary", value="A neutral fictional summary.")
        hook = st.text_input("Hook", value="A neutral hook.")
        why = st.text_input("Why shortable", value="A neutral rationale.")
        submitted = st.form_submit_button("Create project (A)")
    if submitted:
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
            project = ctrl.create_project(_config(), candidate)
            st.session_state["project_id"] = project.project_id
            st.success(f"Created {project.project_id}")
            st.rerun()
        except Exception as exc:  # surfaced to the user, not swallowed
            st.error(f"Create failed: {exc}")


def _stage_button(label: str, action) -> None:
    if st.button(label):
        try:
            action()
            st.rerun()
        except Exception as exc:
            st.error(f"{label} failed: {exc}")


def _d_form(project_id: str) -> None:
    st.subheader("D. Confirm images and rights")
    st.write(
        "Replace `assets/user_images/slot_XXX.png` with your own licensed images, "
        "then confirm rights below. Placeholders are valid PNGs you may keep for a dry run."
    )
    config = _config()
    timeline_path = config.projects_root / project_id / "timeline.json"
    timeline = ctrl.TimelineJson.model_validate(
        json.loads(timeline_path.read_text(encoding="utf-8"))
    )
    with st.form("d_confirm"):
        slot_inputs: dict[str, dict[str, object]] = {}
        all_rights = st.checkbox("I confirm I hold rights for every image", value=True)
        for scene in timeline.scenes:
            st.markdown(f"**{scene.scene_id}** - `{scene.image_path}`")
            note = st.text_input(
                f"Note for {scene.scene_id}",
                value=f"User-owned safe image for {scene.scene_id}.",
                key=f"note_{scene.scene_id}",
            )
            slot_inputs[scene.scene_id] = {
                "actual_image_note": note,
                "rights_confirmed_by_user": all_rights,
            }
        submitted = st.form_submit_button("Confirm D")
    if submitted:
        try:
            if ctrl.current_status(config, project_id) == "project_generated":
                ctrl.init_d(config, project_id)
            payload = ctrl.build_ready_d_payload(timeline, slot_inputs=slot_inputs)
            ctrl.confirm_d(config, project_id, payload)
            st.success("D confirmed")
            st.rerun()
        except Exception as exc:
            st.error(f"Confirm D failed: {exc}")


def _show_f_result(project_id: str) -> None:
    config = _config()
    project_dir = config.projects_root / project_id
    st.success("F Kdenlive skeleton generated.")
    st.write("Open this file in Kdenlive to finish editing manually:")
    st.code(str(project_dir / "project.kdenlive"))
    st.write("Handoff notes:")
    st.code(str(project_dir / "notes" / "manual_kdenlive_editing.md"))


def main() -> None:
    load_local_env()
    st.set_page_config(page_title="Shorts Pipeline", layout="wide")
    st.title("Shorts Pipeline - local A->F")
    _sidebar()

    project_id = st.session_state.get("project_id")
    if not project_id:
        _candidate_form()
        return

    config = _config()
    status = ctrl.current_status(config, project_id)
    st.write(f"Current status: `{status}`")

    if status == "candidate_selected":
        _stage_button("Generate scene plan (B)", lambda: ctrl.run_b(config, project_id))
    elif status == "planned":
        _stage_button("Compile timeline and assets (C)", lambda: ctrl.run_c(config, project_id))
    elif status in {"project_generated", "waiting_for_user_images"}:
        _d_form(project_id)
    elif status == "images_inserted":
        _stage_button("Generate narration and titles (E)", lambda: ctrl.run_e(config, project_id))
    elif status == "script_generated":
        if (config.projects_root / project_id / "project.kdenlive").exists():
            _show_f_result(project_id)
        else:
            _stage_button("Generate Kdenlive skeleton (F)", lambda: ctrl.run_f(config, project_id))
    else:
        st.info(f"No UI action for status `{status}`.")


if __name__ == "__main__":
    main()

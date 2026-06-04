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
from shorts_pipeline.security import ensure_relative_project_path
from shorts_pipeline.ui import controller as ctrl

DEFAULT_BASE_DIR = str(Path(".local").resolve())


def _config() -> ctrl.PipelineConfig:
    base_dir = st.session_state.get("base_dir", DEFAULT_BASE_DIR)
    return ctrl.PipelineConfig.from_base_dir(base_dir)


def _provider_panel() -> None:
    """Render a secret-free real-LLM readiness panel (names only, no values)."""
    info = ctrl.readiness()
    st.sidebar.write(f"Provider mode: `{info['mode']}`")
    if info["ready"]:
        st.sidebar.success(f"Real LLM ready: {info['backend']}")
        return
    if info["real_enabled"] and not info["key_present"]:
        st.sidebar.warning("Real LLM selected but not fully configured; calls will fail.")
    else:
        st.sidebar.caption("Using deterministic fake providers (offline) until configured.")
    lines = ["To enable the real LLM, set these (values are never shown):"]
    lines += [f"- {item}" for item in info["missing"]]
    st.sidebar.info("\n".join(lines))


def _sidebar() -> None:
    st.sidebar.header("Session")
    st.session_state.setdefault("base_dir", DEFAULT_BASE_DIR)
    st.session_state["base_dir"] = st.sidebar.text_input(
        "Local working directory", value=st.session_state["base_dir"]
    )
    _provider_panel()
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
    st.caption(
        "Fill in your own summary/hook, then either create the project and run "
        "stages one by one, or generate the whole draft (A->F) in one click. "
        "One-click uses placeholder images you replace before final editing."
    )
    with st.form("candidate"):
        source_url = st.text_input("Source URL", value="https://example.com/community/post/1")
        community = st.text_input("Community", value="manual")
        title = st.text_input("Source title", value="A safe fictional source title")
        summary = st.text_area("Your summary", value="A neutral fictional summary.")
        hook = st.text_input("Hook", value="A neutral hook.")
        why = st.text_input("Why shortable", value="A neutral rationale.")
        col_a, col_b = st.columns(2)
        created = col_a.form_submit_button("Create project (A)")
        full_draft = col_b.form_submit_button("Generate full draft (A->F)")
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
            with st.spinner("Generating full draft A->F (no rendering, no upload)..."):
                result = ctrl.run_full_pipeline(_config(), candidate)
            st.session_state["project_id"] = result["project_id"]
            st.success(f"Full draft ready: {result['project_id']} ({result['status']})")
        else:
            project = ctrl.create_project(_config(), candidate)
            st.session_state["project_id"] = project.project_id
            st.success(f"Created {project.project_id}")
        st.rerun()
    except Exception as exc:  # surfaced to the user, not swallowed
        action = "Full draft failed" if full_draft else "Create failed"
        st.error(f"{action}: {exc}")


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
        all_rights = st.checkbox(
            "I confirm I hold rights for every image", value=True, key="d_all_rights"
        )
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


def _preview_b(plan) -> None:
    st.subheader("Scene plan (B)")
    st.caption(f"{len(plan.scene_plan)} scenes - target {plan.target_duration_sec}s")
    for scene in plan.scene_plan:
        st.markdown(f"- `{scene.scene_id}` - {scene.duration_sec:g}s - {scene.screen_text}")
        st.caption(scene.narration_intent)


def _preview_c_assets(project_id: str, timeline) -> None:
    st.subheader("Generated assets (C)")
    project_dir = _config().projects_root / project_id
    shown = [
        scene
        for scene in timeline.scenes
        if (project_dir / ensure_relative_project_path(scene.image_path)).is_file()
    ]
    if not shown:
        st.caption("No asset images on disk yet.")
        return
    columns = st.columns(min(3, len(shown)))
    for index, scene in enumerate(shown):
        abs_path = project_dir / ensure_relative_project_path(scene.image_path)
        columns[index % len(columns)].image(str(abs_path), caption=scene.scene_id)


def _preview_e(script) -> None:
    st.subheader("Narration and titles (E)")
    st.success(f"Recommended title: {script.recommended_title}")
    st.markdown("**Title candidates**")
    for candidate in script.title_candidates:
        st.markdown(f"- {candidate.title} _({candidate.angle})_")
    st.markdown("**Narration**")
    for line in script.narration_script:
        st.markdown(f"- `{line.scene_id}` ({line.pace}): {line.script}")


def _render_previews(project_id: str) -> None:
    """Read-only previews of whatever stage artifacts exist on disk."""
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
    except Exception as exc:  # a preview must never take down the whole app
        st.warning(f"Preview unavailable: {exc}")


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

    _render_previews(project_id)

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

"""Streamlit Web UI for Cross-Episode Continuity Checker."""

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from bible import build_bible
from detect import detect_all
from extract import extract_all
from loader import load_episodes
from report import build_report
from verify import get_scene_context, verify_all

# Directory setup
BASE_DIR = Path(__file__).resolve().parent
EPISODES_DIR = BASE_DIR / "data" / "episodes"
OUTPUTS_DIR = BASE_DIR / "outputs"
EPISODES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# Load existing environment
load_dotenv(BASE_DIR / ".env")

st.set_page_config(
    page_title="Cross-Episode Continuity Checker",
    page_icon="🎬",
    layout="wide",
)

# Initialize session state
if "verified_flags" not in st.session_state:
    st.session_state["verified_flags"] = []
if "decisions" not in st.session_state:
    st.session_state["decisions"] = {}

# -------------------------------------------------------------
# SIDEBAR: Configuration & Controls
# -------------------------------------------------------------
st.sidebar.title("⚙️ Checker Settings")

# Provider and Model selection
default_provider = os.getenv("PROVIDER", "openrouter").lower()
providers = ["openrouter", "gemini", "anthropic", "openai"]
provider_index = providers.index(default_provider) if default_provider in providers else 0

selected_provider = st.sidebar.selectbox("Provider", providers, index=provider_index)
os.environ["PROVIDER"] = selected_provider

default_models = {
    "openrouter": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "gemini": "gemini-1.5-flash",
    "anthropic": "claude-3-5-sonnet-20241022",
    "openai": "gpt-4o-mini",
}
env_model = os.getenv("MODEL_NAME", default_models.get(selected_provider, ""))
selected_model = st.sidebar.text_input("Model Name", value=env_model)
os.environ["MODEL_NAME"] = selected_model

# API Key check & optional input
key_env_names = {
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}
key_name = key_env_names.get(selected_provider, "API_KEY")
current_key = os.getenv(key_name, "")
api_key_input = st.sidebar.text_input(
    f"{key_name}",
    value=current_key if current_key and "your_" not in current_key else "",
    type="password",
    help=f"Loaded from .env. You can also paste or override your key here.",
)
if api_key_input:
    os.environ[key_name] = api_key_input

st.sidebar.divider()

# Episodes count & Slider
existing_episodes = load_episodes(EPISODES_DIR)
total_existing = len(existing_episodes)

st.sidebar.subheader("Episode Scope")
if total_existing > 0:
    num_to_process = st.sidebar.slider(
        "Episodes to process",
        min_value=1,
        max_value=max(1, total_existing),
        value=total_existing,
    )
else:
    num_to_process = 1
    st.sidebar.info("Upload episode scripts to enable slider.")

run_clicked = st.sidebar.button("🚀 Run Continuity Check", type="primary", use_container_width=True)

# -------------------------------------------------------------
# MAIN VIEW: Header & Upload Area
# -------------------------------------------------------------
st.title("🎬 Cross-Episode Continuity Checker")
st.caption("AI-assisted continuity supervisor for microdrama series (50+ short episodes).")

# Warning notice as required
st.warning("⚠️ **Notice:** Flags are suggestions for a human reviewer, not final corrections.")

# Upload Area
with st.expander("📁 Upload Episode Screenplays", expanded=(total_existing == 0)):
    uploaded_files = st.file_uploader(
        "Upload episode scripts (.txt, .md, .pdf, .docx)",
        type=["txt", "md", "pdf", "docx"],
        accept_multiple_files=True,
    )
    if uploaded_files:
        for file in uploaded_files:
            dest = EPISODES_DIR / file.name
            with open(dest, "wb") as f:
                f.write(file.getbuffer())
        st.success(f"Successfully uploaded {len(uploaded_files)} file(s) into `data/episodes/`.")
        st.rerun()

    if total_existing > 0:
        st.write(f"**Current files in `data/episodes/` ({total_existing}):**")
        file_list = [f"Ep {ep['episode']}: {ep['filename']} ({len(ep['text'])} chars)" for ep in existing_episodes]
        st.text("\n".join(file_list))

# -------------------------------------------------------------
# PIPELINE EXECUTION
# -------------------------------------------------------------
if run_clicked:
    if not api_key_input and (not current_key or "your_" in current_key):
        st.error(f"Please provide a valid `{key_name}` in the sidebar or in `.env` before running.")
    elif total_existing == 0:
        st.error("No episode files found in `data/episodes/`. Please upload episodes first.")
    else:
        st.subheader("⚙️ Processing Pipeline")
        progress_bar = st.progress(0)
        status_box = st.empty()

        try:
            # Stage 1: Load episodes
            status_box.info("Stage 1/6: Loading and sorting screenplay files...")
            episodes = existing_episodes[:num_to_process]
            progress_bar.progress(15)

            # Stage 2: Fact extraction
            status_box.info(f"Stage 2/6: Extracting story facts from {len(episodes)} episode(s)...")
            all_facts = extract_all(episodes)
            progress_bar.progress(40)

            # Stage 3: Merge story bible
            status_box.info("Stage 3/6: Merging facts into Story Bible...")
            bible = build_bible(all_facts)
            progress_bar.progress(60)

            # Stage 4: Detect contradictions
            status_box.info("Stage 4/6: Detecting candidate contradictions across episodes...")
            raw_flags = detect_all(bible)
            progress_bar.progress(75)

            # Stage 5: Skeptical verification
            status_box.info("Stage 5/6: Verifying flags against original scene scripts...")
            verified_flags = verify_all(raw_flags, episodes)
            progress_bar.progress(90)

            # Stage 6: Build report
            status_box.info("Stage 6/6: Generating markdown and CSV reports...")
            build_report(verified_flags)
            progress_bar.progress(100)

            st.session_state["verified_flags"] = verified_flags
            status_box.success("✅ Continuity check pipeline complete!")

        except Exception as exc:
            status_box.error(f"❌ Error during execution: {exc}")

# -------------------------------------------------------------
# RESULTS & QA EDITOR VIEW
# -------------------------------------------------------------
flags = st.session_state.get("verified_flags", [])

# If session state is empty, check if flags_verified.json already exists from previous runs
if not flags:
    saved_flags_path = OUTPUTS_DIR / "flags_verified.json"
    if saved_flags_path.exists():
        try:
            flags = json.loads(saved_flags_path.read_text(encoding="utf-8"))
            st.session_state["verified_flags"] = flags
        except Exception:
            pass

if flags:
    st.divider()
    st.subheader("📋 Review Flagged Contradictions")

    # Severity and verdict filters
    col_filter1, col_filter2, col_actions = st.columns([2, 2, 4])
    with col_filter1:
        severity_filter = st.selectbox("Filter by Severity", ["All", "Major", "Minor"])
    with col_filter2:
        verdict_filter = st.selectbox("Filter by Verdict", ["All", "Confirmed", "Likely Intentional", "False Alarm"])

    filtered_flags = flags
    if severity_filter != "All":
        filtered_flags = [f for f in filtered_flags if str(f.get("severity", "")).lower() == severity_filter.lower()]
    if verdict_filter != "All":
        verdict_key = verdict_filter.lower().replace(" ", "_")
        filtered_flags = [f for f in filtered_flags if str(f.get("verdict", "")).lower() == verdict_key]

    # Summary table
    table_data = []
    for f in filtered_flags:
        fact_a = f.get("fact_a", {})
        fact_b = f.get("fact_b", {})
        flag_id = f.get("id", "")
        decision = st.session_state["decisions"].get(flag_id, "Pending")
        table_data.append({
            "ID": flag_id,
            "Subject": f.get("subject", ""),
            "Ep A": fact_a.get("episode", ""),
            "Ep B": fact_b.get("episode", ""),
            "Explanation": f.get("explanation", ""),
            "Severity": str(f.get("severity", "")).title(),
            "Confidence": str(f.get("confidence", "")).title(),
            "Verdict": str(f.get("verdict", "")).replace("_", " ").title(),
            "Decision": decision,
        })

    if table_data:
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
    else:
        st.info("No flags match the selected filters.")

    # Detailed row expanders with scene context and Accept/Reject buttons
    episodes_map = {ep["episode"]: ep["text"] for ep in existing_episodes}

    st.markdown("### Detailed Investigation & Human Decision")
    for f in filtered_flags:
        flag_id = f.get("id", "N/A")
        subject = f.get("subject", "N/A")
        verdict = f.get("verdict", "N/A")
        explanation = f.get("explanation", "")
        current_decision = st.session_state["decisions"].get(flag_id, "Pending")

        badge_color = "green" if current_decision == "Accepted" else ("red" if current_decision == "Rejected" else "gray")

        with st.expander(f"**[{flag_id}] {subject.title()}**: {explanation} — Decision: :{badge_color}[{current_decision}]"):
            fact_a = f.get("fact_a", {})
            fact_b = f.get("fact_b", {})

            ep_a = fact_a.get("episode", 0)
            ep_b = fact_b.get("episode", 0)
            ts_a = fact_a.get("timestamp", "")
            ts_b = fact_b.get("timestamp", "")
            q_a = fact_a.get("quote", "")
            q_b = fact_b.get("quote", "")

            scene_a = get_scene_context(episodes_map.get(ep_a, ""), ts_a, q_a)
            scene_b = get_scene_context(episodes_map.get(ep_b, ""), ts_b, q_b)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Fact A (Episode {ep_a}, {ts_a})**")
                st.info(f"**Quote:** \"{q_a}\"")
                st.text_area(f"Scene A Context (Ep {ep_a})", value=scene_a, height=140, key=f"ctx_a_{flag_id}", disabled=True)

            with c2:
                st.markdown(f"**Fact B (Episode {ep_b}, {ts_b})**")
                st.info(f"**Quote:** \"{q_b}\"")
                st.text_area(f"Scene B Context (Ep {ep_b})", value=scene_b, height=140, key=f"ctx_b_{flag_id}", disabled=True)

            st.markdown(f"**Verifier Verdict:** `{verdict}`")
            st.markdown(f"**Verifier Reasoning:** {f.get('reasoning', 'N/A')}")

            # Human QA Action buttons
            btn_col1, btn_col2, _ = st.columns([1, 1, 6])
            with btn_col1:
                if st.button("✅ Accept Flag", key=f"accept_btn_{flag_id}"):
                    st.session_state["decisions"][flag_id] = "Accepted"
                    st.rerun()
            with btn_col2:
                if st.button("❌ Reject Flag", key=f"reject_btn_{flag_id}"):
                    st.session_state["decisions"][flag_id] = "Rejected"
                    st.rerun()

    # ---------------------------------------------------------
    # DOWNLOAD REPORT BUTTONS
    # ---------------------------------------------------------
    st.divider()
    st.subheader("📥 Export Reports")
    rep_col1, rep_col2, _ = st.columns([2, 2, 4])

    md_path = OUTPUTS_DIR / "report.md"
    csv_path = OUTPUTS_DIR / "report.csv"

    if md_path.exists():
        with open(md_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        rep_col1.download_button(
            label="📄 Download report.md",
            data=md_content,
            file_name="continuity_report.md",
            mime="text/markdown",
            use_container_width=True,
        )

    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            csv_content = f.read()
        rep_col2.download_button(
            label="📊 Download report.csv",
            data=csv_content,
            file_name="continuity_report.csv",
            mime="text/csv",
            use_container_width=True,
        )

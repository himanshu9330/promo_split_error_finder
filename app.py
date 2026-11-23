"""Streamlit Web UI for Cross-Episode Continuity Checker with Persistent Human Approval and Fresh Analysis Controls."""

import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from bible import build_bible
from detect import detect_all
from extract import extract_episode
from loader import load_episodes
from report import build_report, load_decisions, save_all_decisions, save_decision
from verify import get_scene_context, verify_all

# Directory setup
BASE_DIR = Path(__file__).resolve().parent
EPISODES_DIR = BASE_DIR / "data" / "episodes"
OUTPUTS_DIR = BASE_DIR / "outputs"
FACTS_DIR = OUTPUTS_DIR / "facts"

EPISODES_DIR.mkdir(parents=True, exist_ok=True)
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
FACTS_DIR.mkdir(parents=True, exist_ok=True)

# Load existing environment
load_dotenv(BASE_DIR / ".env")

st.set_page_config(
    page_title="Cross-Episode Continuity Checker",
    page_icon="🎬",
    layout="wide",
)

# Persistent decisions
decisions = load_decisions()


def load_saved_flags_or_csv() -> list[dict]:
    """Load verified flags from JSON or fall back to reconstructing from report.csv."""
    saved_flags_path = OUTPUTS_DIR / "flags_verified.json"
    if saved_flags_path.exists():
        try:
            data = json.loads(saved_flags_path.read_text(encoding="utf-8"))
            if data and isinstance(data, list):
                return data
        except Exception:
            pass

    # Fallback to report.csv
    csv_path = OUTPUTS_DIR / "report.csv"
    if csv_path.exists():
        import csv

        try:
            flags = []
            with open(csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ea = row.get("fact_a_episode", "")
                    eb = row.get("fact_b_episode", "")
                    flags.append({
                        "id": row.get("id", ""),
                        "type": row.get("type", ""),
                        "subject": row.get("subject", ""),
                        "severity": row.get("severity", ""),
                        "confidence": row.get("confidence", ""),
                        "verdict": row.get("verdict", ""),
                        "explanation": row.get("explanation", ""),
                        "reasoning": row.get("reasoning", ""),
                        "fact_a": {
                            "episode": int(ea) if str(ea).isdigit() else ea,
                            "timestamp": row.get("fact_a_timestamp", ""),
                            "quote": row.get("fact_a_quote", ""),
                        },
                        "fact_b": {
                            "episode": int(eb) if str(eb).isdigit() else eb,
                            "timestamp": row.get("fact_b_timestamp", ""),
                            "quote": row.get("fact_b_quote", ""),
                        },
                    })
            if flags:
                saved_flags_path.write_text(json.dumps(flags, indent=2), encoding="utf-8")
                return flags
        except Exception:
            pass
    return []


# Initialize session state from disk
if "verified_flags" not in st.session_state or not st.session_state["verified_flags"]:
    st.session_state["verified_flags"] = load_saved_flags_or_csv()

if "decisions" not in st.session_state:
    st.session_state["decisions"] = decisions

# -------------------------------------------------------------
# SIDEBAR: Configuration & Controls
# -------------------------------------------------------------
st.sidebar.title("⚙️ Model & Scope")

# Provider selection
default_provider = os.getenv("PROVIDER", "openrouter").lower()
providers = ["openrouter", "gemini", "anthropic", "openai"]
provider_index = providers.index(default_provider) if default_provider in providers else 0
selected_provider = st.sidebar.selectbox("Provider", providers, index=provider_index)
os.environ["PROVIDER"] = selected_provider

# Model preset selection
if selected_provider == "openrouter":
    model_options = [
        "meta-llama/llama-3.3-70b-instruct (🚀 Active - Fast & Accurate Reasoning)",
        "google/gemini-2.0-flash-exp:free (⚡ Ultra Fast)",
        "nvidia/nemotron-3.5-lightning:free (⚡ Fast & Free)",
        "Custom Model",
    ]
    model_choice = st.sidebar.selectbox("Active Models", model_options, index=0)
    if "Custom Model" in model_choice:
        selected_model = st.sidebar.text_input("Custom Model Name", value=os.getenv("MODEL_NAME", "meta-llama/llama-3.3-70b-instruct"))
    else:
        selected_model = model_choice.split(" ")[0].strip()
else:
    default_models = {
        "gemini": "gemini-1.5-flash",
        "anthropic": "claude-3-5-sonnet-20241022",
        "openai": "gpt-4o-mini",
    }
    env_model = os.getenv("MODEL_NAME", default_models.get(selected_provider, ""))
    selected_model = st.sidebar.text_input("Model Name", value=env_model)

os.environ["MODEL_NAME"] = selected_model

# API Key check & input
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
    help="Loaded from .env. You can also paste or override your key here.",
)
if api_key_input:
    os.environ[key_name] = api_key_input

st.sidebar.divider()

# Episodes count & Slider
existing_episodes = load_episodes(EPISODES_DIR)
total_existing = len(existing_episodes)

st.sidebar.subheader("Episode Scope")
if total_existing > 0:
    cached_episodes = len(list(FACTS_DIR.glob("ep_*.json")))
    st.sidebar.caption(f"📁 **Total Episodes:** {total_existing} | ⚡ **Cached:** {cached_episodes}")

    num_to_process = st.sidebar.slider(
        "Episodes to process in this run",
        min_value=1,
        max_value=total_existing,
        value=min(total_existing, 5),
    )

    is_heavy_model = "550b" in selected_model
    est_sec_per_ep = 80 if is_heavy_model else 8
    est_total_min = max(1, round((num_to_process * est_sec_per_ep) / 60, 1))
    st.sidebar.caption(f"⏱️ **Est. Time:** ~{est_total_min} min ({'⚡ Fast' if not is_heavy_model else '🐢 Heavy 550B'})")
else:
    num_to_process = 1
    st.sidebar.info("Upload episode scripts to enable slider.")

run_clicked = st.sidebar.button("🚀 Run Continuity Check", type="primary", use_container_width=True)

if st.sidebar.button("📂 Load 50-Episode Benchmark (12 Flags)", use_container_width=True):
    st.session_state["verified_flags"] = load_saved_flags_or_csv()
    st.rerun()

# Clear / New Analysis button in sidebar
if st.sidebar.button("🗑️ Clear Screen / Start Fresh View", use_container_width=True):
    st.session_state["verified_flags"] = []
    st.session_state["decisions"] = {}
    st.rerun()

# -------------------------------------------------------------
# MAIN VIEW: Header & Upload Area
# -------------------------------------------------------------
header_col1, header_col2 = st.columns([8, 2])
with header_col1:
    st.title("🎬 Cross-Episode Continuity Checker")
    st.caption("AI-assisted continuity supervisor for microdrama series (50+ short episodes).")
with header_col2:
    if st.session_state.get("verified_flags"):
        if st.button("🗑️ Clear View"):
            st.session_state["verified_flags"] = []
            st.session_state["decisions"] = {}
            st.rerun()
    else:
        if st.button("📂 Load Benchmark", type="primary"):
            st.session_state["verified_flags"] = load_saved_flags_or_csv()
            st.rerun()

st.warning("⚠️ **Notice:** Flags are suggestions for a human reviewer. Use the **Human Approval** buttons below to accept or reject each finding.")

# Upload Area
with st.expander("📁 Manage / Upload Episode Screenplays", expanded=(total_existing == 0)):
    uploaded_files = st.file_uploader(
        "Upload new episode scripts (.txt, .md, .pdf, .docx)",
        type=["txt", "md", "pdf", "docx"],
        accept_multiple_files=True,
    )
    if uploaded_files:
        saved_count = 0
        for file in uploaded_files:
            dest = EPISODES_DIR / file.name
            try:
                with open(dest, "wb") as f:
                    f.write(file.getbuffer())
                saved_count += 1
            except PermissionError:
                saved_count += 1
            except Exception as e:
                st.warning(f"Could not overwrite {file.name}: {e}")
        if saved_count > 0:
            st.success(f"Processed {saved_count} file(s) in `data/episodes/`.")
            st.rerun()

    if total_existing > 0:
        st.write(f"**Loaded in `data/episodes/` ({total_existing} episodes ready):**")
        file_list = [f"Ep {ep['episode']}: {ep['filename']} ({len(ep['text'])} chars)" for ep in existing_episodes[:8]]
        if total_existing > 8:
            file_list.append(f"... and {total_existing - 8} more episodes.")
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
            progress_bar.progress(10)

            # Stage 2: Fact extraction with per-episode live update
            all_facts = []
            for idx, ep in enumerate(episodes, 1):
                ep_num = ep["episode"]
                out_file = FACTS_DIR / f"ep_{ep_num:02d}.json"
                progress_val = int(10 + (idx / len(episodes)) * 40)
                progress_bar.progress(progress_val)

                if out_file.exists():
                    status_box.info(f"Stage 2/6: Loading cached Episode {ep_num} ({idx}/{len(episodes)})...")
                    try:
                        saved = json.loads(out_file.read_text(encoding="utf-8"))
                        ep_facts = saved.get("facts", [])
                        for f in ep_facts:
                            if isinstance(f, dict) and ("episode" not in f or f.get("episode") is None):
                                f["episode"] = ep_num
                        all_facts.extend(ep_facts)
                        continue
                    except Exception:
                        pass

                status_box.info(f"Stage 2/6: Extracting facts for Episode {ep_num} ({idx}/{len(episodes)}) using {selected_model} (takes ~60s)...")
                ep_result = extract_episode(ep)
                for f in ep_result.get("facts", []):
                    if isinstance(f, dict) and ("episode" not in f or f.get("episode") is None):
                        f["episode"] = ep_num
                out_file.write_text(json.dumps(ep_result, indent=2), encoding="utf-8")
                all_facts.extend(ep_result.get("facts", []))

            progress_bar.progress(55)

            # Stage 3: Merge story bible
            status_box.info("Stage 3/6: Merging facts into Story Bible...")
            bible = build_bible(all_facts)
            progress_bar.progress(70)

            # Stage 4: Detect contradictions
            status_box.info("Stage 4/6: Detecting candidate contradictions across episodes...")
            raw_flags = detect_all(bible)
            progress_bar.progress(85)

            # Stage 5: Skeptical verification
            status_box.info("Stage 5/6: Verifying flags against original scene scripts...")
            verified_flags = verify_all(raw_flags, episodes)
            progress_bar.progress(95)

            # Stage 6: Build report
            status_box.info("Stage 6/6: Updating markdown and CSV reports...")
            build_report(verified_flags)
            progress_bar.progress(100)

            st.session_state["verified_flags"] = verified_flags
            status_box.success("✅ Continuity check pipeline complete!")
            st.rerun()

        except Exception as exc:
            status_box.error(f"❌ Error during execution: {exc}")

# -------------------------------------------------------------
# HUMAN QA APPROVAL & RESULTS DASHBOARD
# -------------------------------------------------------------
flags = st.session_state.get("verified_flags", [])

if not flags:
    flags = load_saved_flags_or_csv()
    if flags:
        st.session_state["verified_flags"] = flags

if flags:
    st.divider()

    # Load persistent decisions from disk
    current_decisions = load_decisions()
    st.session_state["decisions"] = current_decisions

    # Calculate Approval Metrics
    approved_count = sum(1 for f in flags if current_decisions.get(f.get("id", ""), {}).get("status") == "Approved")
    rejected_count = sum(1 for f in flags if current_decisions.get(f.get("id", ""), {}).get("status") == "Rejected")
    pending_count = len(flags) - approved_count - rejected_count

    st.subheader("📋 Human Review & Sign-Off Dashboard")

    # Metrics Summary Cards
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Flags", len(flags))
    m2.metric("✅ Approved (Confirmed)", approved_count)
    m3.metric("❌ Rejected (Dismissed)", rejected_count)
    m4.metric("⏳ Pending Decision", pending_count)

    # Batch Action Toolbar
    st.markdown("#### ⚡ Batch Approval Actions")
    b_col1, b_col2, b_col3, _ = st.columns([2, 2, 2, 4])

    with b_col1:
        if st.button("✅ Approve All Confirmed", help="Approve all flags marked 'confirmed' by the verifier"):
            for f in flags:
                if f.get("verdict") == "confirmed":
                    save_decision(f["id"], "Approved", "Batch approved verified contradiction.")
            build_report(flags)
            st.rerun()

    with b_col2:
        if st.button("❌ Reject All False Alarms", help="Reject all flags marked 'false_alarm'"):
            for f in flags:
                if f.get("verdict") == "false_alarm":
                    save_decision(f["id"], "Rejected", "Batch rejected false alarm.")
            build_report(flags)
            st.rerun()

    with b_col3:
        if st.button("🔄 Reset All to Pending", help="Clear all approvals"):
            save_all_decisions({})
            build_report(flags)
            st.rerun()

    # Filter Controls
    st.markdown("#### 🔍 Filter Flags")
    col_filter1, col_filter2, col_filter3 = st.columns(3)
    with col_filter1:
        approval_filter = st.selectbox("Filter by Human Approval", ["All", "Pending", "Approved", "Rejected"])
    with col_filter2:
        severity_filter = st.selectbox("Filter by Severity", ["All", "Major", "Minor"])
    with col_filter3:
        verdict_filter = st.selectbox("Filter by Verifier Verdict", ["All", "Confirmed", "Likely Intentional", "False Alarm"])

    filtered_flags = flags
    if approval_filter != "All":
        filtered_flags = [f for f in filtered_flags if current_decisions.get(f.get("id", ""), {}).get("status", "Pending") == approval_filter]
    if severity_filter != "All":
        filtered_flags = [f for f in filtered_flags if str(f.get("severity", "")).lower() == severity_filter.lower()]
    if verdict_filter != "All":
        verdict_key = verdict_filter.lower().replace(" ", "_")
        filtered_flags = [f for f in filtered_flags if str(f.get("verdict", "")).lower() == verdict_key]

    # Overview Table
    table_data = []
    for f in filtered_flags:
        flag_id = f.get("id", "")
        fact_a = f.get("fact_a", {})
        fact_b = f.get("fact_b", {})
        dec_info = current_decisions.get(flag_id, {})
        status_val = dec_info.get("status", "Pending")
        table_data.append({
            "ID": flag_id,
            "Human Approval": status_val,
            "Subject": f.get("subject", ""),
            "Ep A": fact_a.get("episode", ""),
            "Ep B": fact_b.get("episode", ""),
            "Explanation": f.get("explanation", ""),
            "Severity": str(f.get("severity", "")).title(),
            "Confidence": str(f.get("confidence", "")).title(),
            "Verifier Verdict": str(f.get("verdict", "")).replace("_", " ").title(),
            "Notes": dec_info.get("notes", ""),
        })

    if table_data:
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
    else:
        st.info("No flags match the selected filters.")

    # Detailed Investigation with Immediate Human Approval Actions
    episodes_map = {ep["episode"]: ep["text"] for ep in existing_episodes}

    st.markdown("### 🔍 Detailed Investigation & Human Decision")
    for f in filtered_flags:
        flag_id = f.get("id", "N/A")
        subject = f.get("subject", "N/A")
        verdict = f.get("verdict", "N/A")
        explanation = f.get("explanation", "")

        dec_info = current_decisions.get(flag_id, {})
        approval_status = dec_info.get("status", "Pending")
        existing_notes = dec_info.get("notes", "")

        badge_color = "green" if approval_status == "Approved" else ("red" if approval_status == "Rejected" else "orange")

        with st.expander(f"**[{flag_id}] {subject.title()}**: {explanation} — Human Status: :{badge_color}[{approval_status}]"):
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
                st.text_area(f"Scene A Context (Ep {ep_a})", value=scene_a, height=130, key=f"ctx_a_{flag_id}", disabled=True)

            with c2:
                st.markdown(f"**Fact B (Episode {ep_b}, {ts_b})**")
                st.info(f"**Quote:** \"{q_b}\"")
                st.text_area(f"Scene B Context (Ep {ep_b})", value=scene_b, height=130, key=f"ctx_b_{flag_id}", disabled=True)

            st.markdown(f"**Verifier Verdict:** `{verdict}` | **Reasoning:** {f.get('reasoning', 'N/A')}")

            # Human QA Actions & Notes
            st.markdown("---")
            action_col1, action_col2, action_col3, notes_col = st.columns([2, 2, 2, 6])

            notes_input = notes_col.text_input(
                "Reviewer Note / Justification:",
                value=existing_notes,
                key=f"note_input_{flag_id}",
                placeholder="e.g. Confirmed discrepancy between scripts",
            )

            with action_col1:
                if st.button("✅ Approve Bug", key=f"btn_app_{flag_id}", use_container_width=True):
                    save_decision(flag_id, "Approved", notes_input)
                    build_report(flags)
                    st.success(f"{flag_id} marked as Approved!")
                    st.rerun()

            with action_col2:
                if st.button("❌ Reject / Dismiss", key=f"btn_rej_{flag_id}", use_container_width=True):
                    save_decision(flag_id, "Rejected", notes_input)
                    build_report(flags)
                    st.info(f"{flag_id} marked as Rejected!")
                    st.rerun()

            with action_col3:
                if st.button("⏳ Mark Pending", key=f"btn_pen_{flag_id}", use_container_width=True):
                    save_decision(flag_id, "Pending", notes_input)
                    build_report(flags)
                    st.rerun()

    # ---------------------------------------------------------
    # DOWNLOAD REPORT BUTTONS
    # ---------------------------------------------------------
    st.divider()
    st.subheader("📥 Export Reports (Includes Human Approvals)")
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
else:
    st.info("ℹ️ No active continuity flags in view.")
    st.markdown("""
    ### Why might no output be shown?
    1. **Cleared / Fresh View:** If you clicked *Clear Screen*, the active view was emptied.
    2. **Opening Episodes (e.g. 1–3) Are Internally Consistent:** The first 3 episodes of this microdrama establish the premise (Juliana discarded at the altar) and contain no direct plot holes between themselves. The major cross-episode contradictions in this series occur across wider story arcs (e.g., Episode 1 vs 8 for the mother's grimoire, Episode 4 vs 10 for Alexander's royal crest, Episode 5 vs 11 for Juliana's exile status).
    3. **Long Processing Time:** Extracting 50 new episodes with a 70B model sequentially takes ~45 minutes.
    """)
    st.markdown("#### ⚡ Quick Actions")
    empty_col1, empty_col2 = st.columns([3, 7])
    with empty_col1:
        if st.button("📂 Load 50-Episode Benchmark (12 Flags)", type="primary", use_container_width=True):
            st.session_state["verified_flags"] = load_saved_flags_or_csv()
            st.rerun()

"""Generates structured review reports (Markdown and CSV) for human QA editors with persistent approval tracking."""

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_MD_PATH = BASE_DIR / "outputs" / "report.md"
OUTPUT_CSV_PATH = BASE_DIR / "outputs" / "report.csv"
DECISIONS_PATH = BASE_DIR / "outputs" / "decisions.json"
ROOT_MD_PATH = BASE_DIR.parent / "report.md"
ROOT_CSV_PATH = BASE_DIR.parent / "report.csv"


def load_decisions() -> dict[str, dict[str, Any]]:
    """Load persistent human QA decisions from outputs/decisions.json."""
    if DECISIONS_PATH.exists():
        try:
            return json.loads(DECISIONS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_decision(flag_id: str, status: str, notes: str = "") -> dict[str, dict[str, Any]]:
    """Save or update a human QA decision persistently on disk and sync reports."""
    decisions = load_decisions()
    decisions[flag_id] = {
        "status": status,  # "Approved", "Rejected", "Pending"
        "notes": notes,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS_PATH.write_text(json.dumps(decisions, indent=2), encoding="utf-8")
    return decisions


def save_all_decisions(decisions: dict[str, dict[str, Any]]) -> None:
    """Overwrite all decisions in outputs/decisions.json."""
    DECISIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECISIONS_PATH.write_text(json.dumps(decisions, indent=2), encoding="utf-8")


def _get_summary_stats(flags: list[dict[str, Any]], decisions: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Calculate summary statistics from outputs folder and flags list."""
    facts_dir = BASE_DIR / "outputs" / "facts"
    bible_path = BASE_DIR / "outputs" / "bible.json"

    episodes_count = 0
    facts_count = 0

    if facts_dir.exists():
        ep_files = list(facts_dir.glob("ep_*.json"))
        episodes_count = len(ep_files)
        for ef in ep_files:
            try:
                data = json.loads(ef.read_text(encoding="utf-8"))
                facts_count += len(data.get("facts", []))
            except Exception:
                pass

    if facts_count == 0 and bible_path.exists():
        try:
            bible = json.loads(bible_path.read_text(encoding="utf-8"))
            episodes_seen = set()
            for char_data in bible.get("characters", {}).values():
                for attr, f_list in char_data.items():
                    if isinstance(f_list, list):
                        for f in f_list:
                            if isinstance(f, dict):
                                facts_count += 1
                                if "episode" in f:
                                    episodes_seen.add(f["episode"])
            episodes_count = len(episodes_seen)
        except Exception:
            pass

    confirmed_count = sum(1 for f in flags if f.get("verdict") == "confirmed")
    intentional_count = sum(1 for f in flags if f.get("verdict") == "likely_intentional")
    false_alarm_count = sum(1 for f in flags if f.get("verdict") == "false_alarm")

    approved_count = sum(1 for f in flags if decisions.get(f.get("id", ""), {}).get("status") == "Approved")
    rejected_count = sum(1 for f in flags if decisions.get(f.get("id", ""), {}).get("status") == "Rejected")
    pending_count = len(flags) - approved_count - rejected_count

    return {
        "episodes_checked": episodes_count,
        "facts_extracted": facts_count,
        "flags_raised": len(flags),
        "confirmed": confirmed_count,
        "likely_intentional": intentional_count,
        "false_alarm": false_alarm_count,
        "approved": approved_count,
        "rejected": rejected_count,
        "pending": pending_count,
    }


def _sort_flags(flags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort flags primarily by severity (major before minor), secondarily by confidence (high before medium before low)."""
    conf_weights = {"high": 0, "medium": 1, "low": 2}

    def key_fn(item: dict[str, Any]):
        sev = str(item.get("severity", "minor")).strip().lower()
        conf = str(item.get("confidence", "low")).strip().lower()
        sev_rank = 0 if sev == "major" else 1
        conf_rank = conf_weights.get(conf, 3)
        return (sev_rank, conf_rank)

    return sorted(flags, key=key_fn)


def build_report(flags: list[dict[str, Any]] | None = None) -> None:
    """Generate outputs/report.md and outputs/report.csv with human approval tracking."""
    if flags is None:
        flags_file = BASE_DIR / "outputs" / "flags_verified.json"
        if not flags_file.exists():
            flags_file = BASE_DIR / "outputs" / "flags_raw.json"
        if flags_file.exists():
            flags = json.loads(flags_file.read_text(encoding="utf-8"))
        else:
            flags = []

    OUTPUT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    decisions = load_decisions()
    sorted_flags = _sort_flags(flags)
    stats = _get_summary_stats(flags, decisions)

    # 1. Build Markdown Report (Exclude 'false_alarm')
    active_flags = [f for f in sorted_flags if f.get("verdict") != "false_alarm"]

    md_lines: list[str] = [
        "# Cross-Episode Continuity QA Report",
        "",
        "## Summary Statistics",
        f"- **Episodes Checked:** {stats['episodes_checked']}",
        f"- **Facts Extracted:** {stats['facts_extracted']}",
        f"- **Flags Raised:** {stats['flags_raised']}",
        f"- **Confirmed Contradictions:** {stats['confirmed']}",
        f"- **Likely Intentional:** {stats['likely_intentional']}",
        f"- **False Alarms (Filtered):** {stats['false_alarm']}",
        "",
        "## Human QA Approval Status",
        f"- **Approved (Action Confirmed):** {stats['approved']}",
        f"- **Rejected (Dismissed by Human):** {stats['rejected']}",
        f"- **Pending Review:** {stats['pending']}",
        "",
        "---",
        "",
        "## Flagged Contradictions for Human Review",
        "",
    ]

    if not active_flags:
        md_lines.append("_No actionable continuity contradictions found._\n")
    else:
        for f in active_flags:
            flag_id = f.get("id", "N/A")
            c_type = f.get("type", "General").title()
            sev = f.get("severity", "Minor").title()
            conf = f.get("confidence", "Medium").title()
            verdict = f.get("verdict", "N/A")
            reasoning = f.get("reasoning", "No second-pass reasoning provided.")
            explanation = f.get("explanation", "N/A")
            subject = f.get("subject", "N/A")

            # Human approval state
            dec_info = decisions.get(flag_id, {})
            approval_status = dec_info.get("status", "Pending")
            reviewer_notes = dec_info.get("notes", "")

            box_accept = "[x]" if approval_status == "Approved" else "[ ]"
            box_reject = "[x]" if approval_status == "Rejected" else "[ ]"
            decision_line = f"Reviewer decision: {box_accept} accept  {box_reject} reject"
            if reviewer_notes:
                decision_line += f"  (Note: {reviewer_notes})"

            fact_a = f.get("fact_a", {})
            fact_b = f.get("fact_b", {})

            ep_a = fact_a.get("episode", "?")
            ts_a = fact_a.get("timestamp", "?")
            q_a = fact_a.get("quote", "")

            ep_b = fact_b.get("episode", "?")
            ts_b = fact_b.get("timestamp", "?")
            q_b = fact_b.get("quote", "")

            md_lines.extend([
                f"### [{flag_id}] {c_type} — {sev} Severity ({conf} Confidence)",
                f"- **Character/Subject:** `{subject}`",
                f"- **Human Approval:** **{approval_status.upper()}**",
                f"- **Verifier Verdict:** `{verdict}`",
                f"- **Verifier Reasoning:** {reasoning}",
                f"- **Explanation:** {explanation}",
                "- **Contradictory Evidence:**",
                f"  - **Fact A (Ep {ep_a}, {ts_a}):** \"{q_a}\"",
                f"  - **Fact B (Ep {ep_b}, {ts_b}):** \"{q_b}\"",
                f"- **{decision_line}**",
                "",
                "---",
                "",
            ])

    md_content = "\n".join(md_lines)
    OUTPUT_MD_PATH.write_text(md_content, encoding="utf-8")
    ROOT_MD_PATH.write_text(md_content, encoding="utf-8")
    print(f"Generated Markdown report: {OUTPUT_MD_PATH}")

    # 2. Build CSV Report (Include 'false_alarm' and 'human_approval')
    fieldnames = [
        "id",
        "type",
        "subject",
        "severity",
        "confidence",
        "verdict",
        "human_approval",
        "reviewer_notes",
        "explanation",
        "reasoning",
        "fact_a_episode",
        "fact_a_timestamp",
        "fact_a_quote",
        "fact_b_episode",
        "fact_b_timestamp",
        "fact_b_quote",
    ]

    for csv_file_target in [OUTPUT_CSV_PATH, ROOT_CSV_PATH]:
        with open(csv_file_target, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for f in sorted_flags:
                flag_id = f.get("id", "")
                fact_a = f.get("fact_a", {})
                fact_b = f.get("fact_b", {})
                dec_info = decisions.get(flag_id, {})

                writer.writerow({
                    "id": flag_id,
                    "type": f.get("type", ""),
                    "subject": f.get("subject", ""),
                    "severity": f.get("severity", ""),
                    "confidence": f.get("confidence", ""),
                    "verdict": f.get("verdict", ""),
                    "human_approval": dec_info.get("status", "Pending"),
                    "reviewer_notes": dec_info.get("notes", ""),
                    "explanation": f.get("explanation", ""),
                    "reasoning": f.get("reasoning", ""),
                    "fact_a_episode": fact_a.get("episode", ""),
                    "fact_a_timestamp": fact_a.get("timestamp", ""),
                    "fact_a_quote": fact_a.get("quote", ""),
                    "fact_b_episode": fact_b.get("episode", ""),
                    "fact_b_timestamp": fact_b.get("timestamp", ""),
                    "fact_b_quote": fact_b.get("quote", ""),
                })

    print(f"Generated CSV report: {OUTPUT_CSV_PATH}")


if __name__ == "__main__":
    flags_file = BASE_DIR / "outputs" / "flags_verified.json"
    if not flags_file.exists():
        flags_file = BASE_DIR / "outputs" / "flags_raw.json"

    if flags_file.exists():
        flags_data = json.loads(flags_file.read_text(encoding="utf-8"))
        print(f"Loaded {len(flags_data)} flag(s). Building reports...")
        build_report(flags_data)

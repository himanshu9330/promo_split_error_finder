"""Generates structured review reports (Markdown and CSV) for human QA editors."""

import csv
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_MD_PATH = BASE_DIR / "outputs" / "report.md"
OUTPUT_CSV_PATH = BASE_DIR / "outputs" / "report.csv"


def _get_summary_stats(flags: list[dict[str, Any]]) -> dict[str, int]:
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

    return {
        "episodes_checked": episodes_count,
        "facts_extracted": facts_count,
        "flags_raised": len(flags),
        "confirmed": confirmed_count,
        "likely_intentional": intentional_count,
        "false_alarm": false_alarm_count,
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
    """Generate outputs/report.md (excluding false alarms) and outputs/report.csv (including false alarms)."""
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

    sorted_flags = _sort_flags(flags)
    stats = _get_summary_stats(flags)

    # 1. Build Markdown Report (Exclude 'false_alarm')
    active_flags = [f for f in sorted_flags if f.get("verdict") != "false_alarm"]

    md_lines: list[str] = [
        "# Cross-Episode Continuity QA Report",
        "",
        "## Summary",
        f"- **Episodes Checked:** {stats['episodes_checked']}",
        f"- **Facts Extracted:** {stats['facts_extracted']}",
        f"- **Flags Raised:** {stats['flags_raised']}",
        f"- **Confirmed Contradictions:** {stats['confirmed']}",
        f"- **Likely Intentional:** {stats['likely_intentional']}",
        f"- **False Alarms (Filtered):** {stats['false_alarm']}",
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
                f"- **Verifier Verdict:** `{verdict}`",
                f"- **Verifier Reasoning:** {reasoning}",
                f"- **Explanation:** {explanation}",
                "- **Contradictory Evidence:**",
                f"  - **Fact A (Ep {ep_a}, {ts_a}):** \"{q_a}\"",
                f"  - **Fact B (Ep {ep_b}, {ts_b}):** \"{q_b}\"",
                "- **Reviewer decision:** [ ] accept  [ ] reject",
                "",
                "---",
                "",
            ])

    OUTPUT_MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"Generated Markdown report: {OUTPUT_MD_PATH}")

    # 2. Build CSV Report (Include 'false_alarm')
    fieldnames = [
        "id",
        "type",
        "subject",
        "severity",
        "confidence",
        "verdict",
        "explanation",
        "reasoning",
        "fact_a_episode",
        "fact_a_timestamp",
        "fact_a_quote",
        "fact_b_episode",
        "fact_b_timestamp",
        "fact_b_quote",
    ]

    with open(OUTPUT_CSV_PATH, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for f in sorted_flags:
            fact_a = f.get("fact_a", {})
            fact_b = f.get("fact_b", {})
            writer.writerow({
                "id": f.get("id", ""),
                "type": f.get("type", ""),
                "subject": f.get("subject", ""),
                "severity": f.get("severity", ""),
                "confidence": f.get("confidence", ""),
                "verdict": f.get("verdict", ""),
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
        print(f"Loaded {len(flags_data)} flag(s) from {flags_file.name}. Building reports...")
        build_report(flags_data)
    else:
        print("No verified flags found. Generating report with sample flags...")
        sample_flags = [
            {
                "id": "C1",
                "type": "attribute",
                "subject": "riya sharma",
                "severity": "major",
                "confidence": "high",
                "verdict": "confirmed",
                "explanation": "Riya is introduced as a nurse in Ep 1 but claims to be a surgeon in Ep 3.",
                "reasoning": "Original scenes confirm two contradictory professions with no explanation of career change.",
                "fact_a": {"episode": 1, "timestamp": "00:42", "quote": "I work as a nurse at City Hospital."},
                "fact_b": {"episode": 3, "timestamp": "01:15", "quote": "I am a surgeon at Metro Clinic."},
            },
            {
                "id": "C2",
                "type": "status",
                "subject": "vikram",
                "severity": "major",
                "confidence": "high",
                "verdict": "confirmed",
                "explanation": "Vikram is alive in Episode 3 but stated to have passed away last year in Episode 4.",
                "reasoning": "Unexplained death timeline impossibility.",
                "fact_a": {"episode": 3, "timestamp": "00:10", "quote": "Vikram is alive."},
                "fact_b": {"episode": 4, "timestamp": "00:30", "quote": "Vikram passed away last year."},
            },
            {
                "id": "C3",
                "type": "attribute",
                "subject": "boss",
                "severity": "minor",
                "confidence": "low",
                "verdict": "false_alarm",
                "explanation": "Boss mentioned different car colors.",
                "reasoning": "The two scenes describe two distinct company rental vehicles, not his personal car.",
                "fact_a": {"episode": 1, "timestamp": "00:15", "quote": "The black sedan arrived."},
                "fact_b": {"episode": 2, "timestamp": "00:20", "quote": "The white sedan arrived."},
            },
        ]
        build_report(sample_flags)

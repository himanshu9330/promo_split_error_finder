"""Verifies flagged contradictions against original scene scripts as a skeptical second reviewer."""

import json
from pathlib import Path
from typing import Any

from llm import call_model, parse_json
from loader import get_scene_around, load_episodes

BASE_DIR = Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "prompts" / "verify.txt"
OUTPUT_VERIFIED_PATH = BASE_DIR / "outputs" / "flags_verified.json"


def get_scene_context(episode_text: str, timestamp: str, quote: str, window: int = 8) -> str:
    """Retrieve scene text around timestamp or quote with surrounding context lines."""
    if not episode_text:
        return "[Original screenplay text not available]"

    # Attempt 1: Fetch using timestamp
    scene = get_scene_around(episode_text, timestamp, window=window)
    if scene.strip():
        return scene

    # Attempt 2: Fallback to locating quote line
    if quote:
        clean_quote = quote.strip("\"'“”‘’").lower()
        lines = episode_text.splitlines()
        for idx, line in enumerate(lines):
            if clean_quote in line.lower():
                half = window // 2
                start = max(0, idx - half)
                end = min(len(lines), start + window)
                start = max(0, end - window)
                return "\n".join(lines[start:end])

    # Attempt 3: Return excerpt of script
    return "\n".join(episode_text.splitlines()[:window])


def verify_flag(flag: dict[str, Any], episodes_map: dict[int, str]) -> dict[str, Any]:
    """Verify a single contradiction flag against original scenes using an LLM second reviewer."""
    fact_a = flag.get("fact_a", {})
    fact_b = flag.get("fact_b", {})

    ep_a_num = fact_a.get("episode", 0)
    ep_b_num = fact_b.get("episode", 0)

    ts_a = fact_a.get("timestamp", "")
    ts_b = fact_b.get("timestamp", "")

    quote_a = fact_a.get("quote", "")
    quote_b = fact_b.get("quote", "")

    script_a = episodes_map.get(ep_a_num, "")
    script_b = episodes_map.get(ep_b_num, "")

    scene_a = get_scene_context(script_a, ts_a, quote_a)
    scene_b = get_scene_context(script_b, ts_b, quote_b)

    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    formatted_prompt = (
        prompt_template.replace("{flag}", json.dumps(flag, indent=2))
        .replace("{episode_a}", str(ep_a_num))
        .replace("{timestamp_a}", str(ts_a))
        .replace("{scene_a}", scene_a)
        .replace("{episode_b}", str(ep_b_num))
        .replace("{timestamp_b}", str(ts_b))
        .replace("{scene_b}", scene_b)
    )

    response_text = call_model(formatted_prompt, json_mode=True)
    parsed = parse_json(response_text)

    # Attach verification results to the flag
    verdict = parsed.get("verdict", "false_alarm").strip().lower()
    # Normalize verdict string
    if "confirm" in verdict:
        verdict = "confirmed"
    elif "intentional" in verdict:
        verdict = "likely_intentional"
    else:
        verdict = "false_alarm"

    flag["verdict"] = verdict
    flag["reasoning"] = parsed.get("reasoning", "")
    return flag


def verify_all(
    flags: list[dict[str, Any]],
    episodes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Verify all flagged contradictions against the original episodes and save to outputs/flags_verified.json."""
    if episodes is None:
        episodes = load_episodes()

    episodes_map = {ep["episode"]: ep["text"] for ep in episodes}
    verified_list: list[dict[str, Any]] = []

    print(f"Verifying {len(flags)} contradiction flag(s) against original scene scripts...")

    counts = {
        "confirmed": 0,
        "likely_intentional": 0,
        "false_alarm": 0,
    }

    for idx, flag in enumerate(flags, 1):
        flag_id = flag.get("id", f"C{idx}")
        print(f"[{idx}/{len(flags)}] Verifying flag {flag_id}...")
        try:
            verified_flag = verify_flag(flag, episodes_map)
            v = verified_flag.get("verdict", "false_alarm")
            counts[v] = counts.get(v, 0) + 1
            verified_list.append(verified_flag)
            print(f"  -> Result: {v.upper()} | {verified_flag.get('reasoning')}")
        except Exception as e:
            print(f"  -> Error verifying flag {flag_id}: {e}")
            flag["verdict"] = "false_alarm"
            flag["reasoning"] = f"Verification failed with error: {e}"
            counts["false_alarm"] += 1
            verified_list.append(flag)

    # Save to outputs/flags_verified.json
    OUTPUT_VERIFIED_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_VERIFIED_PATH.write_text(json.dumps(verified_list, indent=2), encoding="utf-8")

    print("\n" + "=" * 50)
    print("VERIFICATION COMPLETE:")
    print(f"Total flags checked: {len(verified_list)}")
    print(f"Confirmed: {counts['confirmed']}")
    print(f"Likely Intentional: {counts['likely_intentional']}")
    print(f"False Alarm: {counts['false_alarm']}")
    print(f"Saved verified flags to: {OUTPUT_VERIFIED_PATH}")
    print("=" * 50)

    return verified_list


if __name__ == "__main__":
    flags_path = BASE_DIR / "outputs" / "flags_raw.json"
    if not flags_path.exists():
        print(f"No raw flags found at {flags_path}. Please run detect.py first.")
    else:
        flags_data = json.loads(flags_path.read_text(encoding="utf-8"))
        if not flags_data:
            print("No flags in outputs/flags_raw.json.")
        else:
            verify_all(flags_data)

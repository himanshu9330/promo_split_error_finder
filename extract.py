"""Extracts structured story facts per episode screenplay using an LLM and verifies quote authenticity."""

import json
import re
from pathlib import Path
from typing import Any

from llm import call_model, parse_json
from loader import load_episodes

BASE_DIR = Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "prompts" / "extract.txt"


def normalize_text_for_search(text: str) -> str:
    """Normalize text by converting to lowercase and collapsing consecutive whitespace."""
    if not text:
        return ""
    # Collapse multiple whitespaces/newlines into a single space
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_quote_in_text(quote: str, episode_text: str) -> bool:
    """Check if the extracted quote actually appears in the screenplay, ignoring case and whitespace differences."""
    if not quote or not episode_text:
        return False

    norm_script = normalize_text_for_search(episode_text)
    norm_quote = normalize_text_for_search(quote)

    if norm_quote in norm_script:
        return True

    # Also test stripped outer quotes (e.g. '"Hello"' -> 'hello')
    stripped_quote = normalize_text_for_search(quote.strip("\"'“”‘’"))
    if stripped_quote and stripped_quote in norm_script:
        return True

    return False


def extract_episode(ep: dict[str, Any]) -> dict[str, Any]:
    """Extract story facts from a single episode using call_model, and verify quotes in code."""
    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    formatted_prompt = prompt_template.replace("{episode}", str(ep["episode"])).replace(
        "{screenplay}", ep["text"]
    )

    response_text = call_model(formatted_prompt, json_mode=True)
    parsed = parse_json(response_text)

    # Standardize result structure
    if isinstance(parsed, list):
        facts = parsed
        result = {"episode": ep["episode"], "facts": facts}
    elif isinstance(parsed, dict):
        result = parsed
        if "episode" not in result:
            result["episode"] = ep["episode"]
        if "facts" not in result:
            result["facts"] = []
    else:
        result = {"episode": ep["episode"], "facts": []}

    # Verify each fact's quote in code
    for fact in result.get("facts", []):
        quote = fact.get("quote", "")
        fact["quote_verified"] = verify_quote_in_text(quote, ep["text"])

    return result


def extract_all(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Process episodes one by one, save to outputs/facts/ep_XX.json, skip existing, and return all facts."""
    facts_dir = BASE_DIR / "outputs" / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)

    all_facts: list[dict[str, Any]] = []
    total = len(episodes)

    for idx, ep in enumerate(episodes, 1):
        ep_num = ep["episode"]
        out_file = facts_dir / f"ep_{ep_num:02d}.json"

        if out_file.exists():
            print(f"[{idx}/{total}] Skipping Episode {ep_num} (already extracted at {out_file.name})")
            try:
                saved_data = json.loads(out_file.read_text(encoding="utf-8"))
                ep_facts = saved_data.get("facts", [])
                all_facts.extend(ep_facts)
                continue
            except Exception as e:
                print(f"Error reading existing file {out_file.name}, re-extracting: {e}")

        print(f"[{idx}/{total}] Extracting facts for Episode {ep_num} ({ep['filename']})...")
        ep_result = extract_episode(ep)
        out_file.write_text(json.dumps(ep_result, indent=2), encoding="utf-8")
        all_facts.extend(ep_result.get("facts", []))

    return all_facts


if __name__ == "__main__":
    episodes = load_episodes()
    if not episodes:
        print("No episode files found in data/episodes/. Please add episode files to test.")
    else:
        print(f"Loaded {len(episodes)} episode(s). Running fact extraction...")
        all_facts = extract_all(episodes)
        total_facts = len(all_facts)
        unverified_count = sum(1 for f in all_facts if not f.get("quote_verified", False))

        print("\n" + "=" * 50)
        print("EXTRACTION SUMMARY:")
        print(f"Total facts found: {total_facts}")
        print(f"Facts with quote_verified == True: {total_facts - unverified_count}")
        print(f"Facts with quote_verified == False: {unverified_count}")
        print("=" * 50)

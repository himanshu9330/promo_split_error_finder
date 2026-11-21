"""Analyzes the story bible to identify cross-episode continuity contradictions using targeted LLM checks and quote verification."""

import json
import re
from pathlib import Path
from typing import Any

from bible import find_candidates
from llm import call_model, parse_json

BASE_DIR = Path(__file__).resolve().parent
PROMPT_FILE = BASE_DIR / "prompts" / "detect.txt"
OUTPUT_FLAGS_PATH = BASE_DIR / "outputs" / "flags_raw.json"


def _normalize_quote(text: str) -> str:
    """Normalize quote string for deterministic containment checks."""
    if not text:
        return ""
    cleaned = text.strip().strip("\"'“”‘’")
    return re.sub(r"\s+", " ", cleaned).lower()


def _is_quote_present(quote: str, known_normalized_quotes: set[str]) -> bool:
    """Check if the quote matches any known fact quote in the story bible."""
    norm_q = _normalize_quote(quote)
    if not norm_q:
        return False
    for kq in known_normalized_quotes:
        if norm_q in kq or kq in norm_q:
            return True
    return False


def _collect_all_fact_quotes(bible: dict[str, Any]) -> set[str]:
    """Collect all normalized quotes from characters, events, knowledge, and objects in the bible."""
    quotes = set()
    for char_data in bible.get("characters", {}).values():
        for attr, facts in char_data.items():
            if attr == "aliases" or not isinstance(facts, list):
                continue
            for f in facts:
                if isinstance(f, dict):
                    q = f.get("quote", "")
                    if q:
                        quotes.add(_normalize_quote(q))

    for category in ["events", "knowledge", "objects"]:
        for item in bible.get(category, []):
            if isinstance(item, dict):
                q = item.get("quote", "")
                if q:
                    quotes.add(_normalize_quote(q))

    return quotes


def detect_for_character(name: str, character_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Send only one character's collected facts to the model to detect contradictions."""
    if not character_facts:
        return []

    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    formatted_prompt = prompt_template.replace("{context_title}", f"Character: {name}").replace(
        "{facts}", json.dumps(character_facts, indent=2)
    )

    response_text = call_model(formatted_prompt, json_mode=True)
    parsed = parse_json(response_text)

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "contradictions" in parsed:
        return parsed["contradictions"]
    if isinstance(parsed, dict) and "facts" in parsed:
        return parsed["facts"]
    return []


def detect_events_and_knowledge(events: list[dict[str, Any]], knowledge: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Second pass: checks chronological events and knowledge to catch cross-scene contradictions."""
    combined = sorted(
        events + knowledge,
        key=lambda x: (x.get("episode", 0), x.get("timestamp", "")),
    )
    if not combined:
        return []

    prompt_template = PROMPT_FILE.read_text(encoding="utf-8")
    formatted_prompt = prompt_template.replace(
        "{context_title}", "Chronological Events and Knowledge"
    ).replace("{facts}", json.dumps(combined, indent=2))

    response_text = call_model(formatted_prompt, json_mode=True)
    parsed = parse_json(response_text)

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "contradictions" in parsed:
        return parsed["contradictions"]
    return []


def detect_all(bible: dict[str, Any]) -> list[dict[str, Any]]:
    """Run contradiction detection across character candidate groups and chronological events/knowledge."""
    candidates = find_candidates(bible)
    raw_flags: list[dict[str, Any]] = []

    # Group candidate facts by subject
    char_candidate_map: dict[str, list[dict[str, Any]]] = {}
    for cand in candidates:
        subject = cand["subject"]
        if subject not in char_candidate_map:
            char_candidate_map[subject] = []
        char_candidate_map[subject].extend(cand["facts"])

    # Deduplicate facts per character
    for subject, facts in char_candidate_map.items():
        unique_facts = {f.get("id", str(idx)): f for idx, f in enumerate(facts)}.values()
        char_candidate_map[subject] = list(unique_facts)

    print(f"Running character-level contradiction detection for {len(char_candidate_map)} character(s)...")

    # Pass 1: Character candidate groups
    for idx, (char_name, facts) in enumerate(char_candidate_map.items(), 1):
        print(f"[{idx}/{len(char_candidate_map)}] Checking character: '{char_name}' ({len(facts)} facts)...")
        flags = detect_for_character(char_name, facts)
        for fl in flags:
            fl["subject"] = char_name
        raw_flags.extend(flags)

    # Pass 2: Events and Knowledge
    events = bible.get("events", [])
    knowledge = bible.get("knowledge", [])
    if events or knowledge:
        print(f"Running second pass for chronological events ({len(events)}) and knowledge ({len(knowledge)})...")
        event_flags = detect_events_and_knowledge(events, knowledge)
        for fl in event_flags:
            fl.setdefault("subject", "events/knowledge")
        raw_flags.extend(event_flags)

    # Quote verification: drop flags whose quotes are not in original facts
    known_quotes = _collect_all_fact_quotes(bible)
    verified_flags: list[dict[str, Any]] = []

    for fl in raw_flags:
        quote_a = fl.get("fact_a", {}).get("quote", "")
        quote_b = fl.get("fact_b", {}).get("quote", "")

        has_a = _is_quote_present(quote_a, known_quotes)
        has_b = _is_quote_present(quote_b, known_quotes)

        if not has_a or not has_b:
            print(f"[Dropped Hallucination] Flag rejected because quote was not in facts. Quote A verified: {has_a}, Quote B verified: {has_b}")
            continue

        verified_flags.append(fl)

    # Assign sequential IDs (C1, C2, C3...)
    for idx, fl in enumerate(verified_flags, 1):
        fl["id"] = f"C{idx}"

    # Save to outputs/flags_raw.json
    OUTPUT_FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FLAGS_PATH.write_text(json.dumps(verified_flags, indent=2), encoding="utf-8")

    return verified_flags


if __name__ == "__main__":
    bible_path = BASE_DIR / "outputs" / "bible.json"
    if not bible_path.exists():
        print(f"Story bible not found at {bible_path}. Please run bible.py first.")
    else:
        print(f"Loading story bible from: {bible_path}")
        bible_data = json.loads(bible_path.read_text(encoding="utf-8"))
        try:
            flags = detect_all(bible_data)
            print("\n" + "=" * 50)
            print(f"DETECTION COMPLETE: Found {len(flags)} verified contradiction flag(s):")
            for fl in flags:
                print(f"- [{fl.get('id')}] {fl.get('type')}: {fl.get('explanation')}")
                print(f"  Fact A (Ep {fl.get('fact_a', {}).get('episode')}, {fl.get('fact_a', {}).get('timestamp')}): \"{fl.get('fact_a', {}).get('quote')}\"")
                print(f"  Fact B (Ep {fl.get('fact_b', {}).get('episode')}, {fl.get('fact_b', {}).get('timestamp')}): \"{fl.get('fact_b', {}).get('quote')}\"")
                print(f"  Severity: {fl.get('severity')}, Confidence: {fl.get('confidence')}")
            print("=" * 50)
        except Exception as err:
            print(f"\nModel execution note: {err}")
            print("If you haven't set your OPENROUTER_API_KEY in .env yet, please update .env and re-run.")

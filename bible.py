"""Merges extracted episode facts into a cumulative, cross-referenced story bible using deterministic Python logic."""

import json
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_BIBLE_PATH = BASE_DIR / "outputs" / "bible.json"


def normalize_subject_name(name: str) -> str:
    """Normalize subject names by stripping common titles, punctuation, and converting to lowercase."""
    if not name:
        return ""
    cleaned = name.strip().lower()
    # Strip honorifics and titles
    cleaned = re.sub(
        r"^(?:mr|mrs|ms|miss|dr|doctor|prof|professor|detective|officer|inspector|agent|nurse|lady|lord|sir|noble|count|duke|duchess)\.?\s+",
        "",
        cleaned,
    )
    # Remove extra internal whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def resolve_subject_aliases(subjects: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Merge subjects where one name is contained in another, recording aliases and printing merges."""
    # Find unique normalized names
    unique_names = sorted(list({normalize_subject_name(s) for s in subjects if s}), key=len, reverse=True)

    canonical_map: dict[str, str] = {}
    aliases_map: dict[str, list[str]] = {}

    for name in unique_names:
        if not name:
            continue
        canonical_map[name] = name
        aliases_map[name] = [name]

    # Check for containment merges (e.g. 'riya' contained in 'riya sharma')
    for i in range(len(unique_names)):
        longer = unique_names[i]
        for j in range(i + 1, len(unique_names)):
            shorter = unique_names[j]
            # Avoid re-merging already merged items
            if canonical_map[shorter] != shorter:
                continue

            # Avoid merging a single character into a compound multi-character interaction (e.g. 'juliana' into 'gerald and juliana')
            is_compound_longer = any(sep in longer for sep in [" and ", "/", " & ", ", "])
            is_compound_shorter = any(sep in shorter for sep in [" and ", "/", " & ", ", "])
            if is_compound_longer and not is_compound_shorter:
                continue

            # Avoid merging a character into their possessions, clothing, or objects (e.g. 'juliana' into 'juliana's gown')
            if f"{shorter}'s" in longer or f"{shorter}s'" in longer:
                continue
            item_suffixes = [" gown", " dress", " coat", " ring", " attire", " uniform", " carriage", " cane", " pendant", " necklace"]
            if any(longer.endswith(suff) for suff in item_suffixes):
                continue

            # Check if shorter is contained as a whole word or substring in longer
            if re.search(rf"\b{re.escape(shorter)}\b", longer) or shorter in longer:
                canonical_map[shorter] = longer
                if shorter not in aliases_map[longer]:
                    aliases_map[longer].append(shorter)
                print(f"[Merge] Merged '{shorter}' into '{longer}'")

    return canonical_map, aliases_map


def build_bible(all_facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Build story bible by normalizing names, merging aliases, and grouping facts by (subject, attribute)."""
    raw_subjects = [f.get("subject", "") for f in all_facts if f.get("subject")]
    canonical_map, aliases_map = resolve_subject_aliases(raw_subjects)

    bible: dict[str, Any] = {
        "characters": {},
        "events": [],
        "knowledge": [],
        "objects": [],
    }

    # Group facts
    for fact in all_facts:
        fact_type = fact.get("type", "CHARACTER").upper()
        raw_subject = fact.get("subject", "").strip()
        norm_subject = normalize_subject_name(raw_subject)
        canonical_subject = canonical_map.get(norm_subject, norm_subject)

        attribute = fact.get("attribute", "general").strip().lower()
        if not attribute:
            attribute = "general"

        fact_entry = {
            "id": fact.get("id"),
            "type": fact_type,
            "subject": canonical_subject,
            "original_subject": raw_subject,
            "attribute": attribute,
            "value": fact.get("value"),
            "episode": fact.get("episode"),
            "timestamp": fact.get("timestamp"),
            "source": fact.get("source"),
            "speaker": fact.get("speaker"),
            "reliability": fact.get("reliability", "reliable"),
            "quote": fact.get("quote"),
            "quote_verified": fact.get("quote_verified", True),
        }

        # Place into character structure if subject exists
        if canonical_subject:
            if canonical_subject not in bible["characters"]:
                bible["characters"][canonical_subject] = {
                    "aliases": aliases_map.get(canonical_subject, [canonical_subject])
                }
            if attribute not in bible["characters"][canonical_subject]:
                bible["characters"][canonical_subject][attribute] = []
            bible["characters"][canonical_subject][attribute].append(fact_entry)

        # Also populate top-level lists
        if fact_type == "EVENT":
            bible["events"].append(fact_entry)
        elif fact_type == "KNOWLEDGE":
            bible["knowledge"].append(fact_entry)
        elif "OBJECT" in fact_type or "PLACE" in fact_type:
            bible["objects"].append(fact_entry)

    # Save to outputs/bible.json
    OUTPUT_BIBLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_BIBLE_PATH.write_text(json.dumps(bible, indent=2), encoding="utf-8")

    # Metrics
    num_characters = len(bible["characters"])
    num_attribute_groups = sum(
        len([k for k in attrs if k != "aliases"])
        for attrs in bible["characters"].values()
    )
    candidates = find_candidates(bible)
    num_candidates = len(candidates)

    print("\n" + "=" * 50)
    print("STORY BIBLE SUMMARY:")
    print(f"Number of characters: {num_characters}")
    print(f"Number of attribute groups: {num_attribute_groups}")
    print(f"Number of candidate groups: {num_candidates}")
    print(f"Saved story bible to: {OUTPUT_BIBLE_PATH}")
    print("=" * 50)

    return bible


def find_candidates(bible: dict[str, Any]) -> list[dict[str, Any]]:
    """Return (subject, attribute) groups with 2+ different values, plus STATUS and RELATIONSHIP groups."""
    candidates: list[dict[str, Any]] = []

    # Check total episodes represented in bible
    all_episodes = set()
    for attrs in bible.get("characters", {}).values():
        for facts in attrs.values():
            if isinstance(facts, list):
                for f in facts:
                    if isinstance(f, dict) and f.get("episode") is not None:
                        all_episodes.add(f.get("episode"))

    has_multi_episodes = len(all_episodes) > 1
    transient_attrs = {"question", "statement", "command", "speech", "utterance", "reaction"}

    for subject, attrs in bible.get("characters", {}).items():
        for attr, facts in attrs.items():
            if attr == "aliases" or not isinstance(facts, list):
                continue

            # Skip pure transient dialogue utterances unless they indicate status/relationship
            is_status_or_rel = any(
                f.get("type", "").upper() in ["STATUS", "RELATIONSHIP"]
                or attr in ["status", "relationship", "spouse", "partner", "marital_status", "alive", "dead", "attire", "identity", "rank"]
                for f in facts
            )

            if attr in transient_attrs and not is_status_or_rel:
                continue

            # Distinct normalized values
            distinct_values = {
                str(f.get("value", "")).strip().lower()
                for f in facts
                if f.get("value") is not None
            }

            # Distinct episodes in this group
            episodes_in_facts = {f.get("episode") for f in facts if f.get("episode") is not None}

            # Contradiction candidate condition:
            # 1. 2 or more different values found
            # 2. Or STATUS/RELATIONSHIP facts having 2+ entries across episodes
            has_different_values = len(distinct_values) >= 2
            has_multiple_status_rel = is_status_or_rel and len(facts) >= 2

            if (has_different_values or has_multiple_status_rel):
                # When multiple episodes are present, prioritize groups spanning across episodes
                if has_multi_episodes and len(episodes_in_facts) < 2 and not is_status_or_rel:
                    continue

                candidates.append({
                    "subject": subject,
                    "attribute": attr,
                    "distinct_values": sorted(list(distinct_values)),
                    "fact_count": len(facts),
                    "episodes": sorted(list(episodes_in_facts)),
                    "is_status_or_relationship": is_status_or_rel,
                    "facts": facts,
                })

    return candidates


if __name__ == "__main__":
    facts_dir = BASE_DIR / "outputs" / "facts"
    all_facts: list[dict[str, Any]] = []

    if facts_dir.exists():
        for f in sorted(facts_dir.glob("ep_*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                all_facts.extend(data.get("facts", []))
            except Exception as e:
                print(f"Error reading {f.name}: {e}")

    if all_facts:
        print(f"Loaded {len(all_facts)} fact(s) from outputs/facts/. Building story bible...")
        build_bible(all_facts)
    else:
        print("No facts found in outputs/facts/. Testing with sample facts...")
        sample_facts = [
            {
                "id": "E01-01",
                "type": "CHARACTER",
                "subject": "Riya Sharma",
                "attribute": "job",
                "value": "nurse at City Hospital",
                "episode": 1,
                "timestamp": "00:42",
                "quote": "I work as a nurse at City Hospital.",
                "reliability": "reliable",
            },
            {
                "id": "E03-01",
                "type": "CHARACTER",
                "subject": "Dr. Riya",
                "attribute": "job",
                "value": "surgeon at Metro Clinic",
                "episode": 3,
                "timestamp": "01:15",
                "quote": "I am a surgeon at Metro Clinic.",
                "reliability": "reliable",
            },
            {
                "id": "E03-02",
                "type": "STATUS",
                "subject": "Vikram",
                "attribute": "status",
                "value": "alive",
                "episode": 3,
                "timestamp": "00:10",
                "quote": "Vikram is alive.",
                "reliability": "reliable",
            },
            {
                "id": "E04-01",
                "type": "STATUS",
                "subject": "Vikram",
                "attribute": "status",
                "value": "dead",
                "episode": 4,
                "timestamp": "00:30",
                "quote": "Vikram passed away last year.",
                "reliability": "reliable",
            },
        ]
        build_bible(sample_facts)

"""Command-line runner for the Continuity Checker pipeline on the drama episodes."""

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from loader import load_episodes
from extract import extract_all
from bible import build_bible
from detect import detect_all
from verify import verify_all
from report import build_report


def main(max_episodes: int = 10):
    print("=" * 60)
    print("🎬 RUNNING CONTINUITY CHECKER ON DRAMA EPISODES")
    print(f"Max episodes to process: {max_episodes}")
    print("=" * 60)

    # 1. Load episodes
    episodes = load_episodes()
    if not episodes:
        print("No episodes found in data/episodes/.")
        return

    selected = episodes[:max_episodes]
    print(f"Loaded {len(episodes)} total episodes. Processing first {len(selected)}...")

    # 2. Extract facts
    start_t = time.time()
    print("\n--- STAGE 1: FACT EXTRACTION ---")
    all_facts = extract_all(selected)
    print(f"Extracted {len(all_facts)} total facts across {len(selected)} episodes in {time.time() - start_t:.1f}s.")

    # 3. Build Story Bible
    print("\n--- STAGE 2: STORY BIBLE GENERATION ---")
    bible = build_bible(all_facts)

    # 4. Detect Contradictions
    print("\n--- STAGE 3: CONTRADICTION DETECTION ---")
    raw_flags = detect_all(bible)
    print(f"Detected {len(raw_flags)} raw candidate flags.")

    # 5. Skeptical Verification
    print("\n--- STAGE 4: SKEPTICAL VERIFICATION ---")
    verified_flags = verify_all(raw_flags, selected)

    # 6. Generate Report
    print("\n--- STAGE 5: REPORT GENERATION ---")
    build_report(verified_flags)

    print("\n" + "=" * 60)
    print("✅ PIPELINE EXECUTION COMPLETE!")
    print("Check outputs/report.md and outputs/report.csv")
    print("=" * 60)


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    main(count)

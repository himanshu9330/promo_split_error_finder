"""Reads and parses episode screenplay files from text, markdown, PDF, and DOCX formats."""

import os
import re
from pathlib import Path
from typing import Any


def _extract_text_from_file(file_path: Path) -> str:
    """Read file content based on extension (.txt, .md, .pdf, .docx)."""
    ext = file_path.suffix.lower()

    if ext in [".txt", ".md"]:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="latin-1")

    elif ext == ".pdf":
        try:
            import pdfplumber
        except ImportError as e:
            raise ImportError("pdfplumber is required to parse PDF scripts. Install via: pip install pdfplumber") from e

        pages_text: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
        return "\n".join(pages_text)

    elif ext == ".docx":
        try:
            import docx
        except ImportError as e:
            raise ImportError("python-docx is required to parse DOCX scripts. Install via: pip install python-docx") from e

        doc = docx.Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs)

    return ""


def _extract_episode_number(filename: str) -> int | None:
    """Extract episode number from filename using common patterns (e.g., ep_03, Episode 3, E03)."""
    stem = Path(filename).stem
    # Match patterns like ep_03, episode 3, E03, ep-4
    match = re.search(r"(?:ep(?:isode)?|[e])[\s\-_]*(\d+)", stem, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))

    # Fallback: any standalone numbers or digits in the filename
    match_digits = re.search(r"(\d+)", stem)
    if match_digits:
        return int(match_digits.group(1))

    return None


def load_episodes(folder: str | Path = "data/episodes") -> list[dict[str, Any]]:
    """Read every .txt, .md, .pdf and .docx file in folder and return sorted episode dicts."""
    folder_path = Path(folder)
    if not folder_path.is_absolute():
        # Resolve relative to project root or current working directory
        project_dir = Path(__file__).resolve().parent
        if (project_dir / folder_path).exists():
            folder_path = project_dir / folder_path

    if not folder_path.exists():
        print(f"Warning: Folder '{folder_path}' does not exist.")
        return []

    valid_extensions = {".txt", ".md", ".pdf", ".docx"}
    all_files = [f for f in folder_path.iterdir() if f.is_file() and f.suffix.lower() in valid_extensions]

    if not all_files:
        return []

    numbered_files: list[tuple[int, Path]] = []
    unnumbered_files: list[Path] = []

    for f in all_files:
        ep_num = _extract_episode_number(f.name)
        if ep_num is not None:
            numbered_files.append((ep_num, f))
        else:
            print(f"Warning: No episode number found in filename '{f.name}'. Assigning based on alphabetical order.")
            unnumbered_files.append(f)

    # Sort unnumbered files alphabetically and assign numbers following the highest existing number (or starting at 1)
    unnumbered_files.sort(key=lambda p: p.name.lower())
    start_num = max([num for num, _ in numbered_files], default=0) + 1
    for offset, f in enumerate(unnumbered_files):
        numbered_files.append((start_num + offset, f))

    # Sort all files by episode number
    numbered_files.sort(key=lambda item: item[0])

    episodes: list[dict[str, Any]] = []
    for ep_num, file_path in numbered_files:
        text = _extract_text_from_file(file_path)
        episodes.append({
            "episode": ep_num,
            "text": text,
            "filename": file_path.name,
        })

    return episodes


def get_scene_around(episode_text: str, timestamp: str, window: int = 6) -> str:
    """Return ~window lines surrounding the line where timestamp appears. Returns empty string if not found."""
    if not timestamp or timestamp not in episode_text:
        return ""

    lines = episode_text.splitlines()
    target_idx = -1
    for idx, line in enumerate(lines):
        if timestamp in line:
            target_idx = idx
            break

    if target_idx == -1:
        return ""

    half = window // 2
    start = max(0, target_idx - half)
    end = min(len(lines), start + window)
    # Ensure window lines are captured if near the end of text
    start = max(0, end - window)

    return "\n".join(lines[start:end])


if __name__ == "__main__":
    episodes_dir = Path(__file__).resolve().parent / "data" / "episodes"
    print(f"Checking for episode files in: {episodes_dir}")
    loaded = load_episodes(episodes_dir)

    if not loaded:
        print("No episode files found in data/episodes/. Add .txt, .md, .pdf, or .docx files to test.")
    else:
        print(f"Found {len(loaded)} episode(s):\n" + "-" * 50)
        for ep in loaded:
            print(f"Episode: {ep['episode']}")
            print(f"Filename: {ep['filename']}")
            print(f"Character Count: {len(ep['text'])}")
            print(f"First 200 characters:\n{ep['text'][:200]}")
            print("-" * 50)

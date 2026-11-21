# Cross-Episode Continuity Checker

A tool for detecting narrative and factual continuity errors across AI-generated microdrama series (typically 50+ episodes of 1-2 minutes with timestamps).

## Pipeline Architecture

1. **Loader (`loader.py`)**: Ingests screenplay files from `.txt`, `.pdf`, or `.docx` formats.
2. **Fact Extraction (`extract.py`)**: Runs episode scripts through LLM-based fact extraction (`prompts/extract_facts.txt`) to capture characters, relationships, status, events, knowledge, and key objects with timestamps and quotes.
3. **Story Bible (`bible.py`)**: Merges all episode fact lists into an aggregated, cross-referenced story bible (`prompts/merge_bible.txt`).
4. **Contradiction Detection (`detect.py`)**: Performs cross-episode comparison (`prompts/detect_contradictions.txt`) to detect timeline, status, knowledge, and attribute contradictions.
5. **Verification (`verify.py`)**: Acts as a skeptical second reviewer (`prompts/verify_flag.txt`), checking flags against raw scenes to eliminate false alarms.
6. **Reporting & UI (`report.py`, `app.py`)**: Presents findings in an interactive Streamlit dashboard and exports structured reports for human QA editors.
7. **Evaluation (`evaluate.py`)**: Evaluates system performance using planted-error benchmark tests.

## Setup & Installation

Requires Python 3.10+.

```bash
# Navigate to project directory
cd continuity-checker

# Create and activate a virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

## Running the App

```bash
streamlit run app.py
```

"""
Stage 3: Existing Data Separation

Reads data_all_labeled.json and removes entries that already exist in
llm_results_with_annotated_data_2510.json, outputting only the unprocessed
remainder to output/data_remaining.json.

Identity key: (tool_name, project_name_with_version, file_path, line_number)
"""

import json
from pathlib import Path

INPUT_DIR = Path(__file__).parent / "input"
OUTPUT_DIR = Path(__file__).parent / "output"

LABELED_FILE = INPUT_DIR / "data_all_labeled.json"
EXISTING_FILE = INPUT_DIR / "llm_results_with_annotated_data_2510.json"
OUTPUT_FILE = OUTPUT_DIR / "data_remaining.json"
STATS_FILE = OUTPUT_DIR / "stats.json"


def make_key(entry: dict) -> tuple:
    return (
        entry["tool_name"],
        entry["project_name_with_version"],
        entry["file_path"],
        entry["line_number"],
    )


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Loading {EXISTING_FILE.name} ...", flush=True)
    with open(EXISTING_FILE, encoding="utf-8") as f:
        existing = json.load(f)

    existing_keys = {make_key(e) for e in existing}
    print(f"  Already processed: {len(existing_keys)} unique entries")

    print(f"Loading {LABELED_FILE.name} ...", flush=True)
    with open(LABELED_FILE, encoding="utf-8") as f:
        labeled = json.load(f)
    print(f"  Total labeled warnings: {len(labeled)}")

    remaining = [e for e in labeled if make_key(e) not in existing_keys]
    skipped = len(labeled) - len(remaining)

    print(f"  Skipped (already processed): {skipped}")
    print(f"  Remaining (new work):        {len(remaining)}")

    print(f"Writing {OUTPUT_FILE.name} ...", flush=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(remaining, f, ensure_ascii=False, indent=2)

    stats = {
        "total_labeled": len(labeled),
        "already_processed": skipped,
        "remaining": len(remaining),
    }
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print("Done.")
    print(f"  Output → {OUTPUT_FILE}")
    print(f"  Stats  → {STATS_FILE}")


if __name__ == "__main__":
    main()


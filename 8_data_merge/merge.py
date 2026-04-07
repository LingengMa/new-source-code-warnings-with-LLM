"""
Stage 8: Data Merge
Merges old (previous/) and new data into two output files:
  1. merged_annotated.json  — only manually annotated inconsistent entries (old 1025 + new 873)
  2. merged_all.json        — all entries (old 2510 + new 2386)

ID assignment rules:
  - Old entries keep their original IDs (1-2510) unchanged.
  - New entries are remapped to IDs starting from old_max_id + 1.
"""

import json
import os

INPUT_DIR = "input"
OUTPUT_DIR = "output"

OLD_ALL_FILE = os.path.join(INPUT_DIR, "previous", "llm_results_with_annotated_data_2510.json")
OLD_ANNOT_FILE = os.path.join(INPUT_DIR, "previous", "llm_results_with_annotated_data_1025.json")
NEW_ALL_FILE = os.path.join(INPUT_DIR, "llm_results_with_annotated_data_2386.json")
NEW_ANNOT_FILE = os.path.join(INPUT_DIR, "llm_results_with_annotated_data_873.json")

OUT_ALL = os.path.join(OUTPUT_DIR, "merged_all.json")
OUT_ANNOT = os.path.join(OUTPUT_DIR, "merged_annotated.json")

os.makedirs(OUTPUT_DIR, exist_ok=True)


def load(path):
    print(f"Loading {path}...")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_entry(entry):
    """Ensure consistent key order across old/new entries."""
    canonical_keys = [
        "id", "tool_name", "project_name", "project_name_with_version",
        "project_version", "file_path", "line_number", "cwe", "rule_id",
        "message", "severity", "function_name", "label", "llm_results",
        "sliced_code", "manual_annotation", "annotation_reason", "annotation_timestamp",
    ]
    result = {}
    for k in canonical_keys:
        if k in entry:
            result[k] = entry[k]
    # Include any extra keys not in the canonical list
    for k, v in entry.items():
        if k not in result:
            result[k] = v
    return result


def main():
    old_all = load(OLD_ALL_FILE)
    old_annot = load(OLD_ANNOT_FILE)
    new_all = load(NEW_ALL_FILE)
    new_annot = load(NEW_ANNOT_FILE)

    print(f"Old all:   {len(old_all)} entries")
    print(f"Old annot: {len(old_annot)} entries")
    print(f"New all:   {len(new_all)} entries")
    print(f"New annot: {len(new_annot)} entries")

    # Determine the starting ID for new entries
    old_max_id = max(e["id"] for e in old_all)
    print(f"\nOld max ID: {old_max_id}")
    print(f"New entries will start at ID: {old_max_id + 1}")

    # Build ID remap for new_all: original_id -> new_id
    id_remap = {}
    next_id = old_max_id + 1
    for entry in new_all:
        id_remap[entry["id"]] = next_id
        next_id += 1

    # --- Build merged_all ---
    merged_all = []

    for entry in old_all:
        merged_all.append(normalize_entry(entry))

    for entry in new_all:
        e = dict(entry)
        e["id"] = id_remap[e["id"]]
        merged_all.append(normalize_entry(e))

    print(f"\nMerged all: {len(merged_all)} entries")

    # --- Build merged_annotated ---
    # new_annot IDs are a subset of new_all IDs; remap them
    new_annot_ids = set(e["id"] for e in new_annot)
    assert new_annot_ids.issubset(set(e["id"] for e in new_all)), \
        "new_annot contains IDs not present in new_all"

    merged_annot = []

    for entry in old_annot:
        merged_annot.append(normalize_entry(entry))

    for entry in new_annot:
        e = dict(entry)
        e["id"] = id_remap[e["id"]]
        merged_annot.append(normalize_entry(e))

    print(f"Merged annotated: {len(merged_annot)} entries")

    # Sanity checks
    all_ids = [e["id"] for e in merged_all]
    assert len(all_ids) == len(set(all_ids)), "Duplicate IDs in merged_all!"

    annot_ids = set(e["id"] for e in merged_annot)
    all_ids_set = set(all_ids)
    assert annot_ids.issubset(all_ids_set), "merged_annot has IDs not in merged_all!"

    # Write outputs
    print(f"\nWriting {OUT_ALL}...")
    with open(OUT_ALL, "w", encoding="utf-8") as f:
        json.dump(merged_all, f, ensure_ascii=False, indent=2)

    print(f"Writing {OUT_ANNOT}...")
    with open(OUT_ANNOT, "w", encoding="utf-8") as f:
        json.dump(merged_annot, f, ensure_ascii=False, indent=2)

    print("\nDone.")
    print(f"  {OUT_ALL}: {len(merged_all)} entries")
    print(f"  {OUT_ANNOT}: {len(merged_annot)} entries")


if __name__ == "__main__":
    main()

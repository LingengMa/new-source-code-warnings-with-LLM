# Stage 8: Data Merge

Merges old (stage 7 output, `input/previous/`) and new processed data into unified output files, then performs multi-dimensional analysis.

## Input Files

| File | Description | Count |
|------|-------------|-------|
| `input/previous/llm_results_with_annotated_data_2510.json` | All old entries | 2510 |
| `input/previous/llm_results_with_annotated_data_1025.json` | Old inconsistent entries (manually annotated) | 1025 |
| `input/llm_results_with_annotated_data_2386.json` | All new entries | 2386 |
| `input/llm_results_with_annotated_data_873.json` | New inconsistent entries (manually annotated) | 873 |

**Inconsistency criterion**: the algorithm label (`label` field) disagrees with at least one of the four LLM classification results.

## Output Files

| File | Description | Count |
|------|-------------|-------|
| `output/merged_all.json` | All entries (old + new) | 4896 |
| `output/merged_annotated.json` | Manually annotated inconsistent entries (old + new) | 1898 |
| `output/analysis.json` | Analysis data (JSON) | — |
| `output/analysis.md` | Analysis report (Markdown) | — |

## ID Assignment

- Old entries keep their original IDs (1–2510) **unchanged**.
- New entries are assigned IDs starting from 2511 (i.e., `old_max_id + 1`).
- The same new IDs appear in both `merged_all.json` and `merged_annotated.json`.

## Environment Setup

This stage uses only Python standard library (no external dependencies).

```bash
conda create -n data_merge python=3.11 -y
```

## Running

```bash
# Merge old and new data
python merge.py       # → output/merged_all.json, output/merged_annotated.json

# Analyze merged data
python analyze.py     # → output/analysis.json, output/analysis.md
```

## Documentation

- `docs/merge_design.md` — detailed design notes for the merge logic

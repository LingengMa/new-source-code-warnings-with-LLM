# Merge Design Notes

## Source Files

| Variable | Path | Role |
|----------|------|------|
| `old_all` | `input/previous/llm_results_with_annotated_data_2510.json` | All old entries |
| `old_annot` | `input/previous/llm_results_with_annotated_data_1025.json` | Old inconsistent (manually annotated) subset |
| `new_all` | `input/llm_results_with_annotated_data_2386.json` | All new entries |
| `new_annot` | `input/llm_results_with_annotated_data_873.json` | New inconsistent (manually annotated) subset |

## ID Remapping

Old entries keep IDs 1–2510 unchanged. New entries receive IDs starting at `old_max_id + 1 = 2511`, assigned in the order they appear in `new_all`. The same remap is applied to entries in `new_annot` (which is a subset of `new_all`).

## Inconsistency Criterion

An entry is "inconsistent" when the algorithm label (`label` field, set by stage 2) disagrees with **at least one** of the four LLM classification results stored in `llm_results`:

```
wuwl  — 三分类, with algorithm label
wuol  — 三分类, without algorithm label
ouwl  — 二分类, with algorithm label
ouol  — 二分类, without algorithm label
```

This was verified empirically: all 873 entries in `new_annot` satisfy this criterion against entries in `new_all`.

## Final Label Logic (analysis.py)

Priority: `manual_annotation` (if non-null/non-empty) > algorithm `label`.

## Key Assertions

- No duplicate IDs in `merged_all.json`.
- All IDs in `merged_annotated.json` are a subset of IDs in `merged_all.json`.
- All IDs in `new_annot` are a subset of IDs in `new_all`.

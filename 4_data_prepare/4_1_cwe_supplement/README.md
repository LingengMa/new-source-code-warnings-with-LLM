# Stage 4_1: CWE Information Supplement

Fills empty `cwe` fields in `data_remaining.json` by matching each warning's
`rule_id` against tool-specific CWE reference files.

## Scripts

| Script | Purpose |
|--------|---------|
| `supplement.py` | Main script: fills empty `cwe` fields using tool-specific lookup tables |
| `analyze_cppcheck_rules.py` | Analysis: enumerates all cppcheck rule_ids, checks each against all CWE sources, outputs `output/cppcheck_rule_analysis.json` |

## Input / Output

| File | Description |
|------|-------------|
| `input/data_remaining.json` | 430,496 warnings from stage 3 |
| `input/cwe_information/` | CWE reference data per tool |
| `output/data_remaining_cwe_supplement.json` | Full dataset with CWEs filled where possible |
| `output/supplement_stats.json` | Per-tool counts: total / had CWE / supplemented / still missing |
| `output/cppcheck_rule_analysis.json` | All 137 cppcheck rule_ids: mapping status, CWE, entry counts, justification |

## Environment Setup

No external dependencies — standard library only.

```bash
conda create -n cwe_supplement python=3.11 -y
```

## Running

```bash
cd 4_data_prepare/4_1_cwe_supplement
python supplement.py              # fill CWEs → output/data_remaining_cwe_supplement.json
python analyze_cppcheck_rules.py  # rule analysis → output/cppcheck_rule_analysis.json
```

Output is written to the `output/` directory.

## Results (last run)

| Tool | Total | Already had CWE | Supplemented | Still missing |
|------|-------|-----------------|-------------|---------------|
| codeql | 44,593 | 14,738 | 29,855 | 0 |
| cppcheck | 376,932 | 154,364 | 333 | 222,235 |
| csa | 8,264 | 0 | 8,264 | 0 |
| semgrep | 707 | 707 | 0 | 0 |
| **Total** | **430,496** | **169,809** | **38,452** | **222,235** |

The 222,235 still-missing cppcheck entries correspond to 9 diagnostic rule IDs (analysis
limitations, tool errors, missing headers) with no applicable CWE. `returnImplicitInt`
(204 entries) was assigned CWE-758 via semantic analysis — see `docs/design.md`.

## See Also

- `docs/design.md` — mapping strategy and coverage analysis
- `prompt.md` — original task specification

## Explanation

![image-20260403020038962](https://typora-picture-host-lingengma.oss-cn-beijing.aliyuncs.com/img/image-20260403020038962.png)

![image-20260403020057743](https://typora-picture-host-lingengma.oss-cn-beijing.aliyuncs.com/img/image-20260403020057743.png)

余下空 CWE 条目应当直接滤除.

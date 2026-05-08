# Stage 4_2: Warning Data Filter

Filters the CWE-supplemented dataset from stage 4_1 down to a clean subset
relevant for vulnerability annotation.

## Scripts

| Script | Purpose |
|--------|---------|
| `filter.py` | Applies all four filters sequentially, writes output files |

## Input / Output

| File | Description |
|------|-------------|
| `input/data_remaining_cwe_supplement.json` | 430,496 warnings from stage 4_1 |
| `input/cwe-top25` | CWE top-25 list (text file with CWE-NNN tokens) |
| `input/repository/` | Symlink to source repositories for `#include` lookup |
| `output/data_filtered.json` | Final filtered dataset |
| `output/filter_stats.json` | Counts before/after each filter step |
| `output/analysis.json` | Distribution by CWE, project, tool, label (JSON) |
| `output/analysis.md` | Human-readable distribution summary |

## Environment Setup

```bash
conda create -n data_filter python=3.11 -y
conda run -n data_filter pip install packaging
```

## Running

```bash
cd 4_data_prepare/4_2_data_filter
conda run -n data_filter python filter.py
```

Output is written to `output/`.

## Filter Pipeline

Filters are applied in this order:

1. **CWE top25** — keep entries whose `cwe` list intersects the top-25 set
2. **Test files** — drop entries from test/fuzz/benchmark source files
3. **`#include` lines** — drop entries whose target source line is a `#include`
4. **Last version** — drop entries from the latest known version of each project

See `docs/design.md` for detailed rationale.

## Results (last run)

| Step | Before | After | Dropped |
|------|--------|-------|---------|
| 1 — CWE top25 | 430,496 | 3,245 | 427,251 |
| 2 — test files | 3,245 | 3,140 | 105 |
| 3 — #include | 3,140 | 3,140 | 0 |
| 4 — last version | 3,140 | 2,386 | 754 |
| **Final** | | **2,386** | |

Distribution: cppcheck 1,277 · csa 925 · semgrep 184  
Dominant CWE: CWE-476 (2,147), CWE-20 (155), CWE-416 (55)  
Note: codeql contributes 0 entries — its rules map to code-quality CWEs (e.g. CWE-1120) that are not in the top-25.

## See Also

- `docs/design.md` — filter design decisions and per-project test pattern rationale
- `prompt.md` — original task specification

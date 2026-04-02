# Copilot Instructions

## Project Overview

This is a thesis dataset construction pipeline that extracts, matches, and annotates static analysis warnings from C projects for vulnerability research. The pipeline processes raw output from 4 static analysis tools across 10 open-source C projects (curl, ffmpeg, git, libuv, musl, nginx, openssl, redis, tmux, vim) with multiple versions each.

## Pipeline Architecture

The workflow is a sequential 7-stage pipeline, each stage in its own numbered directory:

```
1_extractor               → Extract raw tool warnings → output/data_all.json
2_algorithm_match         → Algorithm-based lifecycle labeling (TP/FP/Unknown) → output/data_all_labeled.json
3_existing_data_separation→ Separate already-processed warnings from new work → output/
4_data_prepare            → Filter/normalize (CWE top25, remove test/define warnings, remove last version)
5_slice                   → Code slice extraction via Joern
6_llm_match               → LLM-based matching
7_annotate                → Manual annotation
```

Each stage reads from the previous stage's output. All stage scripts are Python. **All program output goes to the `output/` directory within each stage.** Documentation (beyond README) goes in `docs/`.

### Stage conventions (applies to all stages)
- Each stage has its own conda environment and `requirements.txt`
- Each stage may contain a `prompt.md` describing the original task specification
- **If input data looks wrong, fix it upstream — the downstream stage must not adapt around bad input data**

## Running the Stages

Each stage uses its own conda environment. Run scripts from within the stage directory.

```bash
# Stage 1 — extraction
conda run -n extractor python extract.py       # → output/data_all.json
conda run -n extractor python analyze.py       # → output/analysis.md

# Stage 1 env setup
conda create -n extractor python=3.11 -y
conda run -n extractor pip install beautifulsoup4 lxml

# Stage 2 — algorithm matching
conda run -n matcher python tracker.py        # → output/data_all_labeled.json

# Stage 2 env setup (packaging required for version sorting)
conda create -n matcher python=3.11 -y
conda run -n matcher pip install packaging

# Stage 3 — existing data separation
python separate.py    # → output/data_remaining.json
# Filters data_all_labeled.json against llm_results_with_annotated_data_2510.json
# Identity key: tool_name + project_name_with_version + file_path + line_number
```

## Unified Warning Schema

All extracted warnings conform to this structure (see `1_extractor/input/sample.json`):

```json
{
  "tool_name": "semgrep|codeql|cppcheck|csa",
  "project_name": "curl",
  "project_name_with_version": "curl-8_11_1",
  "project_version": "8.11.1",
  "file_path": "src/foo.c",
  "line_number": 42,
  "cwe": ["CWE-20"],
  "rule_id": "...",
  "message": "...",
  "severity": "WARNING|ERROR|..."
}
```

Stage 2 input (`data_all.json` copied as `data_with_id.json` after adding UUIDs) adds a UUID `id` field per warning. Stage 2 output (`data_all_labeled.json`) further adds a `label` field: `TP`, `FP`, or `Unknown`.

## Stage 2: Algorithm Matching Design

`match.py` contains the `Matcher` class with a 4-level cascading match strategy (exact → location → snippet → hash). `tracker.py` contains `LifecycleTracker` which orchestrates the full lifecycle:

- Groups warnings by `project_name`, sorts versions using `packaging.version`
- For each warning in version V_i, checks all subsequent versions V_i+1…V_n
- **FP**: matched in any later version (warning persists = likely false positive)
- **TP**: unmatched in all later versions (warning disappears = likely fixed)
- **Unknown**: appears only in the last known version (no later version to compare)

`Matcher` reads source files from `input/repository/<project_name>/<project_version>/<file_path>`. Match type is recorded (`exact`/`location`/`snippet`/`hash`) in `match_stats`.

## Raw Warning Data Formats

Located in `1_extractor/input/data/<tool>/<project>/`:

| Tool | Format | Notes |
|------|--------|-------|
| **CodeQL** | `.sarif` (JSON-based SARIF) | `<project>-<version>_codeql.sarif` |
| **Cppcheck** | `.xml` | `<project>-<version>.xml` |
| **CSA** (Clang Static Analyzer) | HTML | `index.html` + per-report HTML files in a versioned directory |
| **Semgrep** | `.json` | `<project>-<version>_semgrep.json` |

An empty directory for a tool/project combination means that tool found no bugs in that version.

**CSA limitation**: HTML only provides the filename (no full path), so `file_path` is filename only and `cwe` is always `[]`.

**FFmpeg CSA special case**: directories named `FFmpeg-n<version>` — normalize to lowercase `ffmpeg` and strip the `n` prefix from the version.

**Cppcheck/Semgrep path handling**: raw `file_path` is an absolute path (e.g. `/mnt/c/.../curl-curl-8_7_1/src/foo.c`). Truncate to the relative path by finding the project-name segment in the path.

## Version Naming Convention

**Critical:** `project_name_with_version` must match the actual directory name in `input/repository/` and `public/repository/`. Directory naming differs by project:

- **curl only**: uses underscores — `curl-8_11_1`
- **All other projects**: use dots — `ffmpeg-7.1.1`, `git-2.44.0`, `libuv-1.46.0`, etc.

Raw data filenames always use dots (e.g., `curl-8.11.1_codeql.sarif`). When building `project_name_with_version` for curl, convert dots to underscores; for all other projects keep dots.

## Resource Locations

- `public/repository/` — source code for all project versions (used for slice extraction in stage 4)
- `public/annotations_raw/data/` — original raw warning data (same as `1_extractor/input/data/`)
- `1_extractor/input/repository/` — symlink/copy of source repos for stage 1 use
- `1_extractor/input/data/项目版本.xlsx` — spreadsheet of all project versions

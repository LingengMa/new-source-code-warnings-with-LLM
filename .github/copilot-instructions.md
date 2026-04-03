# Copilot Instructions

## Project Overview

This is a thesis dataset construction pipeline that extracts, matches, and annotates static analysis warnings from C projects for vulnerability research. The pipeline processes raw output from 4 static analysis tools across 10 open-source C projects (curl, ffmpeg, git, libuv, musl, nginx, openssl, redis, tmux, vim) with multiple versions each.

## Pipeline Architecture

The workflow is a sequential 7-stage pipeline, each stage in its own numbered directory:

```
1_extractor               ✅ → Extract raw tool warnings → output/data_all.json
2_algorithm_match         ✅ → Algorithm-based lifecycle labeling (TP/FP/Unknown) → output/data_all_labeled.json
3_existing_data_separation✅ → Separate already-processed warnings from new work → output/data_remaining.json
4_data_prepare            ✅ → Sub-stages (4_1_cwe_supplement, …) for filter/normalize → output/data_filtered.json
5_slice/slice_joern       ✅ → Code slice extraction via Joern → output/slices_for_llm_with_label.json
6_llm_match               ✅ → DeepSeek LLM classification (4 modes) → output/results_*.json
7_annotate                📋 → Manual annotation
```

Stage 4 is organized as **numbered sub-directories** (`4_1_cwe_supplement/`, `4_2_…/`, etc.), each with its own `input/`, `output/`, `prompt.md`, and conda environment.

Each stage reads from the previous stage's output. All stage scripts are Python. **All program output goes to the `output/` directory within each stage.** Documentation (beyond README) goes in `docs/`.

### Stage conventions (applies to all stages)
- Each stage has its own conda environment and `requirements.txt`
- Each stage may contain a `prompt.md` describing the original task specification
- Documentation beyond README goes in `docs/` within each stage
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

# Stage 3 — no external deps, standard library only
python separate.py    # → output/data_remaining.json + output/stats.json
# Filters data_all_labeled.json against llm_results_with_annotated_data_2510.json
# Identity key: tool_name + project_name_with_version + file_path + line_number

# Stage 4_1 — CWE supplement
cd 4_data_prepare/4_1_cwe_supplement
conda create -n cwe_supplement python=3.11 -y   # standard library only, no pip deps
conda run -n cwe_supplement python supplement.py              # → output/data_remaining_cwe_supplement.json + output/supplement_stats.json
conda run -n cwe_supplement python analyze_cppcheck_rules.py  # → output/cppcheck_rule_analysis.json

# Stage 4_2 — Data filtering
cd 4_data_prepare/4_2_data_filter
conda create -n data_filter python=3.11 -y && conda run -n data_filter pip install packaging
conda run -n data_filter python filter.py  # → output/data_filtered.json + filter_stats.json + analysis.*

# Stage 5 — Code slice extraction (Joern)
cd 5_slice/slice_joern
# Requires Joern installed at /opt/joern-cli and the 'slice' conda env
conda activate slice
python single_file_slicer.py   # → output/slices.json (with checkpoint resume)
python recover_failed.py       # retry entries with status="error" from a previous run
python show_progress.py        # display progress from output/progress.json

# Stage 5 env setup
conda create -n slice python=3.11 -y
conda run -n slice pip install -r requirements.txt
# tree-sitter-languages is needed for AST enhancement (recommended):
conda run -n slice pip install tree-sitter-languages

# Stage 6 — LLM classification (requires DEEPSEEK_API_KEY env variable)
cd 6_llm_match
python llm.py --mode with_unknown_without_label     # 三分类, no algorithm label
python llm.py --mode without_unknown_without_label  # 二分类, no algorithm label
python llm.py --mode with_unknown_with_label        # 三分类, with algorithm label
python llm.py --mode without_unknown_with_label     # 二分类, with algorithm label

# Validate that all project_name_with_version values map to real repo directories
# conda run -n extractor python validate_repo_paths.py   (run from 1_extractor/)
```

## Utilities

### utils/cwe-information/

Converts CWE mapping spreadsheets (XLSX) to JSON for consumption by stage 4:

```bash
cd utils/cwe-information
python excel_to_json.py   # converts all input/*.xlsx → output/*.json (mirrors directory structure)
```

Tool-specific mappings available: CodeQL (C/Java/Python), Cppcheck, Semgrep, CSA, Bandit, Horusec, SpotBugs. Output is consumed by `4_data_prepare/4_1_cwe_supplement/input/cwe_information/`.

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

## Stage 4: Data Preparation Sub-Stages

Stage 4 is a multi-step sub-pipeline. Each sub-stage feeds the next:

```
4_1_cwe_supplement  → data_remaining_cwe_supplement.json
4_2_data_filter     → (TBD, reads 4_1 output)
```

### Stage 4_1: CWE Supplement

Fills empty `cwe` fields in `data_remaining.json` via `rule_id` lookups. Strategy per tool:

| Tool | Source file | Key field | Coverage |
|------|-------------|-----------|----------|
| codeql | `cwe_information/codeql/merged_codeql_C_report.json` | `ruleId` → `rule.properties.tags` | 100% |
| cppcheck | `cwe_information/merged_cppcheck_report.json` | `id` → integer `cwe` | partial (9 diagnostic rule_ids have no CWE) |
| csa | `cwe_information/csa_merged_cwe.json` | `Bug Type` = `rule_id` | 100% |
| semgrep | — | already complete | — |

CWE values are **never overwritten** — only empty `cwe` lists are filled. Format: `["CWE-NNN"]`.

The 222,235 cppcheck entries that remain empty after supplement all correspond to tool-internal diagnostic rule IDs (e.g. `internalError`, `missingInclude`, `syntaxError`). These have no applicable CWE and should be **filtered out** in stage 4_2.

### Stage 4_2: Data Filtering ✅

Reads `4_1_cwe_supplement/output/data_remaining_cwe_supplement.json`. Applies filters in this order:

1. **CWE top25**: keep only entries whose `cwe` list intersects `input/cwe-top25` (drop entries with empty `cwe` here too)
2. **Test files**: drop entries where `file_path` is a test file (patterns vary by project — analyze before hardcoding)
3. **`#define` lines**: look up `input/repository/<project_name_with_version>/<file_path>` at `line_number`; drop if the line is a `#define`
4. **Last version**: for each `project_name`, identify the latest version and drop all its entries
5. **Analysis**: after filtering, output distribution stats by CWE, project, and tool

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

- `public/repository/` — source code for all project versions (used for slice extraction in stage 5)
- `public/annotations_raw/data/` — original raw warning data (same as `1_extractor/input/data/`)
- `1_extractor/input/repository/` — symlink/copy of source repos for stage 1 use
- `1_extractor/input/data/项目版本.xlsx` — spreadsheet of all project versions

## Stage 5: Code Slice Extraction

Located in `5_slice/slice_joern/`. Reads `input/data_filtered.json` and `input/repository/` (source repos); writes to `output/`.

**Joern dependency**: requires Joern installed at `/opt/joern-cli` (provides `joern-parse` and `joern-export`).

### Module Roles

| File | Role |
|------|------|
| `single_file_slicer.py` | Entry point. `JoernAnalyzer` calls Joern per file; `SingleFileSlicer` orchestrates multi-process slicing with checkpoint resume |
| `pdg_loader.py` | Parses Joern-exported DOT files into `PDG`/`PDGNode` graph objects |
| `slice_engine.py` | Core PDG-based backward/forward slice traversal (`SliceEngine`) |
| `ast_enhancer.py` | Uses tree-sitter to ensure sliced lines form syntactically valid code (bracket balancing, if-else completeness) |
| `code_extractor.py` | Assembles final slice string; inserts `PLACEHOLDER` comments for omitted lines; extracts called function definitions |
| `function_extractor.py` | Regex-based fallback for extracting called function definitions from source |
| `treesitter_extractor.py` | tree-sitter-based accurate function extractor (preferred over `function_extractor.py`) |
| `code_recoverer.py` | Replaces `PLACEHOLDER` comments back with original code (for LLM output post-processing) |
| `config.py` | Central configuration: all paths, depths, feature flags, and per-rule depth overrides |

### Key Configuration (`config.py`)

- **Input/output paths** use `input/` and `output/` (standard pipeline convention)
- **`BACKWARD_DEPTH`/`FORWARD_DEPTH`** default to 10; override per `rule_id` prefix via `RULE_SLICE_DEPTH_OVERRIDES`
- **`ENABLE_AST_FIX`**: tree-sitter AST enhancement (on by default)
- **`ENABLE_DEF_USE_AUGMENTATION`**: augment slices with def-use chains for assignment LHS at the warning line (on by default)
- **`EMPTY_SLICE_FALLBACK`**: fall back to ±`CONTEXT_SIZE` lines if PDG yields no nodes (on by default)
- **`EXTRACT_FUNCTION_CALLS`**: append called function definitions to slice output (on by default)
- **`NUM_PROCESSES`**: parallel worker count (default 5); **`ENABLE_CHECKPOINT`**: resume from `output/checkpoint.json`
- **`CHUNK_SIZE`**: saves every 100 completed tasks to allow mid-run inspection

### Slice Output Schema

Each entry in `output/slices.json` extends the warning schema with:

```json
{
  "slice_code": "...",
  "slice_lines": [1, 5, 7],
  "function_name": "curl_easy_setopt",
  "function_definitions": { "helper_fn": "..." }
}
```

Stage 5 also writes `output/slices_for_llm.json` (no label) and `output/slices_for_llm_with_label.json` (with label), which are the inputs for stage 6.

## Stage 6: LLM Matching

Located in `6_llm_match/`. Reads `input/slices_for_llm_with_label.json` and calls the DeepSeek API to classify each warning.

**Requires** `DEEPSEEK_API_KEY` environment variable. Uses `deepseek-chat` model with `response_format={'type': 'json_object'}` (DeepSeek JSON Output mode).

### Four Modes

| Mode | Classes | Algorithm label included |
|------|---------|--------------------------|
| `with_unknown_without_label` | TP/FP/Unknown | No |
| `without_unknown_without_label` | TP/FP | No |
| `with_unknown_with_label` | TP/FP/Unknown | Yes |
| `without_unknown_with_label` | TP/FP | Yes |

Each mode reads from the same input file but uses a different prompt module from `prompts/`. Results are saved to `output/results_<mode>.json`. All four modes should be run on each dataset.

Checkpoint resume is built-in: re-running a mode skips already-processed IDs. Progress is auto-saved every 10 entries; 5 parallel workers via `ThreadPoolExecutor`.

After running all four modes, merge results:

```bash
cd 6_llm_match
python merge.py  # → output/results_merged.json + output/analysis.json + output/analysis.md
```

`merge.py` combines the four result files into a single JSON where each entry gains a `llm_results` field keyed by short codes: `wuwl` (三分类+含算法标签), `wuol` (三分类+不含算法标签), `ouwl` (二分类+含算法标签), `ouol` (二分类+不含算法标签). `output/results_merged.json` is the input for stage 7.

## Stage 7: Manual Annotation

Located in `7_annotate/`. Targets entries where the 5 labels (1 algorithm + 4 LLM modes) are not fully consistent.

### Data flow

```
input/results_merged.json  →  prepare_data.py  →  data.json (stage root)
data.json + input/repository/  →  src/app.py (Flask)  →  annotations.json (stage root)
```

### Running

```bash
# 1. Prepare the subset requiring annotation
cd 7_annotate
conda run -n annotate python prepare_data.py   # → data.json in stage root

# 2. Launch the annotation web app
cd src
conda activate annotate
python app.py   # → http://localhost:5000
```

### Stage 7 env setup

```bash
conda create -n annotate python=3.11 -y
conda run -n annotate pip install -r src/requirements.txt
# requirements: Flask==3.0.0, Flask-CORS==4.0.0
```

### Key paths (relative to stage root `7_annotate/`)

| Path | Description |
|------|-------------|
| `input/results_merged.json` | Output of stage 6 `merge.py` |
| `data.json` | Filtered subset for annotation (created by `prepare_data.py`) |
| `annotations.json` | Annotation results written by the Flask app |
| `input/repository/` | Source code repos (for displaying file content in UI) |
| `src/app.py` | Flask web server; reads `data.json`, writes `annotations.json` |
| `src/templates/index.html` | Frontend annotation UI |

The app exposes: `GET /api/warnings`, `GET /api/stats`, `POST /api/annotate`, `DELETE /api/delete_annotation/<id>`, `GET /api/file`, `GET /api/export`.

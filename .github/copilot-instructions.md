# Copilot Instructions

## Project Overview

This is a thesis dataset construction pipeline that extracts, matches, and annotates static analysis warnings from C projects for vulnerability research. The pipeline processes raw output from 4 static analysis tools across 10 open-source C projects (curl, ffmpeg, git, libuv, musl, nginx, openssl, redis, tmux, vim) with multiple versions each.

## Pipeline Architecture

The workflow is a sequential 6-stage pipeline, each stage in its own numbered directory:

```
1_extractor      → Extract raw tool warnings → data_all.json
2_algorithm_match → Algorithm-based warning matching
3_data_prepare   → Filter/normalize (CWE top25, remove test/define warnings, remove last version)
4_slice          → Code slice extraction via Joern
5_llm_match      → LLM-based matching
6_annotate       → Manual annotation
```

Each stage reads from the previous stage's output. Stage scripts are typically Python.

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

## Raw Warning Data Formats

Located in `1_extractor/input/data/<tool>/<project>/`:

| Tool | Format | Notes |
|------|--------|-------|
| **CodeQL** | `.sarif` (JSON-based SARIF) | `<project>-<version>_codeql.sarif` |
| **Cppcheck** | `.xml` | `<project>-<version>.xml` |
| **CSA** (Clang Static Analyzer) | HTML | `index.html` + per-report HTML files in a versioned directory |
| **Semgrep** | `.json` | `<project>-<version>_semgrep.json` |

An empty directory for a tool/project combination means that tool found no bugs in that version.

## Version Naming Convention

**Critical:** Repository directories use underscores in version numbers (e.g., `curl-8_11_1`), while raw data filenames use dots (e.g., `curl-8.11.1`). The `project_name_with_version` field in extracted JSON **must use the underscore format** to align with `1_extractor/input/repository/` and `public/repository/` for downstream source code extraction.

## Resource Locations

- `public/repository/` — source code for all project versions (used for slice extraction in stage 4)
- `public/annotations_raw/data/` — original raw warning data (same as `1_extractor/input/data/`)
- `1_extractor/input/repository/` — symlink/copy of source repos for stage 1 use
- `1_extractor/input/data/项目版本.xlsx` — spreadsheet of all project versions

## Stage 1 Task (current active work)

See `1_extractor/prompt.md`. The goal is to write Python scripts that:
1. Parse all 4 tool formats and produce `data_all.json` (list of warning objects)
2. Analyze the extracted data: per-tool, per-version, per-CWE statistics exported as Markdown

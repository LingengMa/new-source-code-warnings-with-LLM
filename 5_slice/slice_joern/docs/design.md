# Design: Stage 5 — Joern-based Code Slicing

## Overview

Each entry in `input/data_filtered.json` is a static analysis warning with a `file_path` and `line_number`. This stage extracts the minimal relevant code context (a "slice") for each warning using Program Dependence Graph (PDG) analysis.

## Module Responsibilities

| Module | Role |
|--------|------|
| `single_file_slicer.py` | Entry point. `JoernAnalyzer` invokes Joern per file; `SingleFileSlicer` manages multi-process execution and checkpoint resume |
| `pdg_loader.py` | Parses Joern-exported DOT files into `PDG` / `PDGNode` objects |
| `slice_engine.py` | PDG traversal: `SliceEngine.backward_slice()` / `forward_slice()` |
| `ast_enhancer.py` | tree-sitter pass that closes open `if`/`for`/`while`/`switch` brackets and preserves complete if-else chains containing the warning line |
| `code_extractor.py` | Assembles the final code string; inserts `PLACEHOLDER` comments for omitted lines; calls function extractors |
| `treesitter_extractor.py` | Accurate tree-sitter-based extraction of called function definitions (preferred) |
| `function_extractor.py` | Regex-based fallback for called function extraction |
| `code_recoverer.py` | Replaces `PLACEHOLDER` markers back with original code (for LLM output post-processing) |
| `config.py` | All path, depth, and feature-flag configuration |

## Slicing Pipeline (per warning)

```
Source file  →  JoernAnalyzer (joern-parse + joern-export)
             →  PDGLoader (parse DOT → PDG graph)
             →  SliceEngine (backward + forward PDG traversal)
             →  ASTEnhancer (tree-sitter bracket/branch completion)
             →  CodeExtractor (assemble slice string + called functions)
             →  result dict (merged with input fields)
```

If PDG traversal yields no nodes (`EMPTY_SLICE_FALLBACK=True`), a ±`CONTEXT_SIZE` line window around the warning is used instead.

## Error Fallback Hierarchy

For every warning, slicing is attempted in this order:

1. **PDG slice** — backward + forward traversal (`BACKWARD_DEPTH` / `FORWARD_DEPTH`)
2. **AST variable slice** — if PDG gives empty/trivial result, tree-sitter traces def-use of the warning-line assignment
3. **Context extraction** — ±`CONTEXT_SIZE` lines around the warning line (status: `context_fallback`), triggered when:
   - PDG gives empty/trivial result AND AST slice also fails
   - No PDG exists for the target line
   - Source file is not at the expected path but is found via basename search within the project repository

If the source file cannot be located at all, the entry remains `status: "error"`.

`recover_failed.py` can be run after the fact to apply context extraction to any `status: "error"` entries already in `output/slices.json`.

## Joern Integration

`JoernAnalyzer` copies the source file into a temporary directory, then calls:
1. `joern-parse --language c <dir>` → generates `.bin` CPG
2. `joern-export --repr pdg --out pdg/ <dir>` → exports PDG DOT files
3. `joern-export --repr cfg --out cfg/ <dir>` → exports CFG DOT files
4. `joern-export --repr cpg14 --out cpg/ <dir>` → exports CPG DOT files

All Joern output lands in a `tempfile.mkdtemp()` directory that is deleted after each task.

## Output Schema

Each entry in `output/slices.json` carries all original input fields plus:

```json
{
  "status": "success | error",
  "function_name": "...",
  "function_start_line": 42,
  "function_end_line": 99,
  "sliced_code": "...",
  "slice_lines": [44, 47, 51],
  "enhanced_slice_lines": [44, 45, 47, 51],
  "called_functions": ["helper_fn"],
  "function_definitions": { "helper_fn": "..." },
  "complete_code": "...",
  "metadata": { ... }
}
```

`complete_code` = `sliced_code` with called function definitions appended.

## Parallelism & Checkpointing

- `NUM_PROCESSES` workers run via `multiprocessing.Pool`
- Results are flushed to `output/slices_chunk_NNNN.json` every `CHUNK_SIZE` tasks
- `output/checkpoint.json` tracks which task indices are complete; re-running resumes from there
- `output/progress.json` is updated after each chunk for external monitoring (`show_progress.py`)

## Per-Rule Depth Overrides

`RULE_SLICE_DEPTH_OVERRIDES` in `config.py` maps `rule_id` prefixes to `{"backward": N, "forward": M}`, allowing tighter or wider slices for specific vulnerability classes without changing the global defaults.

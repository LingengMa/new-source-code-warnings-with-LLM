# Stage 5 — Code Slice Extraction (Joern)

Reads `input/data_filtered.json` from stage 4_2, performs PDG-based backward/forward slicing on each warning's source file via Joern, and writes results to `output/`.

## Prerequisites

- **Joern** installed at `/opt/joern-cli` (provides `joern-parse` and `joern-export`)
- Conda environment `slice` (see below)
- Source repositories symlinked under `input/repository/`

## Environment Setup

```bash
conda create -n slice python=3.11 -y
conda run -n slice pip install -r requirements.txt
# tree-sitter-languages is required for AST enhancement:
conda run -n slice pip install tree-sitter-languages
```

## Running

```bash
conda activate slice
python single_file_slicer.py   # → output/slices.json (+ chunk files, checkpoint, progress)

# If any entries have status="error" in a previous run, recover them with:
python recover_failed.py       # → patches output/slices.json in-place, rebuilds derived files
```

Checkpoint/resume is enabled by default. Re-running after interruption picks up where it left off via `output/checkpoint.json`.

## Output Files

| File | Description |
|------|-------------|
| `output/slices.json` | Merged final result (all input fields + slice fields) |
| `output/slices_summary.json` | Lightweight summary per entry |
| `output/slices_for_llm.json` | Slim format for LLM input (no label) |
| `output/slices_for_llm_with_label.json` | Slim format for LLM input (with label) |
| `output/slices_chunk_NNNN.json` | Intermediate chunk files saved every 100 tasks |
| `output/checkpoint.json` | Checkpoint for resume |
| `output/progress.json` | Progress tracking |

## Configuration

All parameters are in `config.py`. Key knobs:

- `BACKWARD_DEPTH` / `FORWARD_DEPTH` — PDG slice depth (default 10)
- `RULE_SLICE_DEPTH_OVERRIDES` — per-rule depth overrides
- `NUM_PROCESSES` — parallel workers (default 5)
- `ENABLE_CHECKPOINT` — checkpoint/resume (default `True`)
- `EMPTY_SLICE_FALLBACK` — fall back to ±`CONTEXT_SIZE` line window if PDG yields nothing (default `True`)
- `EXTRACT_FUNCTION_CALLS` — append called function definitions (default `True`)
- `ENABLE_AST_FIX` — use tree-sitter to ensure syntactic validity (default `True`)

See `docs/design.md` for architecture details.

# Stage 6 Design Notes

## Overview

Stage 6 sends each code slice (from stage 5) to a DeepSeek LLM for TP/FP classification. Four prompt configurations are run independently and then merged into a single result per warning.

## Four Classification Modes

| Key | Mode name | Classes | Algorithm label |
|-----|-----------|---------|-----------------|
| `wuwl` | `with_unknown_with_label` | TP/FP/Unknown | Yes |
| `wuol` | `with_unknown_without_label` | TP/FP/Unknown | No |
| `ouwl` | `without_unknown_with_label` | TP/FP | Yes |
| `ouol` | `without_unknown_without_label` | TP/FP | No |

Running all four modes provides:
- Comparison of forced binary (TP/FP) vs. allowing Unknown
- Comparison of LLM reasoning with vs. without the algorithm-generated reference label

## JSON Output Mode

The API is called with `response_format={'type': 'json_object'}`, which guarantees valid JSON output without requiring explicit format instructions in the prompt. This replaces the previous approach of appending format instructions to the user message and manually parsing the response.

The prompt is split across two messages:
- **system**: The full analysis instructions (`PROMPT_TEMPLATE` from each prompt module)
- **user**: The JSON-serialized warning data

## Prompt Design

Each prompt instructs the LLM to return exactly three fields: `id`, `llm_label`, `llm_label_reason`.

For modes that include the algorithm label (`wl`), the prompt explains the label's origin and limitations, and instructs the LLM to use it as supplementary reference only — code analysis takes precedence.

For `Unknown` modes, the prompt gives strict criteria for when Unknown is appropriate (missing critical dataflow information in the slice) and explicitly discourages using Unknown as a default when inference from the slice is possible.

## Merge Strategy

`merge.py` reads all four raw output files and constructs a single entry per warning ID:
- Top-level fields come from the original warning schema (tool, project, file, CWE, etc.)
- `llm_results` dict contains one entry per mode (keyed by `wuwl`/`wuol`/`ouwl`/`ouol`)
- If a mode file is missing or a particular ID was not processed in one mode, that mode key is omitted from `llm_results`

## Checkpoint/Resume

Each mode supports resume: on startup, `llm.py` loads any existing output file and skips IDs already present. Progress is auto-saved every 10 processed entries.

## Concurrency

5 parallel `ThreadPoolExecutor` workers per mode. Each worker handles one warning independently with up to 3 retries on API errors.

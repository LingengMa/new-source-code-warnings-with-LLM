# Stage 6 — LLM Matching

Classifies each static analysis warning from stage 5 as **TP**, **FP**, or **Unknown** using the DeepSeek LLM, across four prompt configurations.

## Prerequisites

- `DEEPSEEK_API_KEY` environment variable must be set.
- Input file: `input/slices_for_llm_with_label.json` (from stage 5 output).

## Environment Setup

```bash
conda create -n llm_match python=3.11 -y
conda run -n llm_match pip install -r requirements.txt
```

## Running

### Step 1 — Run all four classification modes

Each mode can be run independently (supports checkpoint resume):

```bash
export DEEPSEEK_API_KEY=<your_key>

python llm.py --mode with_unknown_without_label     # 三分类, no algorithm label
python llm.py --mode without_unknown_without_label  # 二分类, no algorithm label
python llm.py --mode with_unknown_with_label        # 三分类, with algorithm label
python llm.py --mode without_unknown_with_label     # 二分类, with algorithm label
```

Each mode writes to its own file in `output/`. Re-running a mode skips already-processed IDs (checkpoint resume via existing output file).

### Step 2 — Merge results and generate analysis

```bash
python merge.py
```

## Output Files

| File | Description |
|------|-------------|
| `output/results_with_unknown_with_label.json` | 三分类 + 含算法标签 raw results |
| `output/results_with_unknown_without_label.json` | 三分类 + 不含算法标签 raw results |
| `output/results_without_unknown_with_label.json` | 二分类 + 含算法标签 raw results |
| `output/results_without_unknown_without_label.json` | 二分类 + 不含算法标签 raw results |
| `output/results_merged.json` | **Final merged result** (all fields + `llm_results` dict) |
| `output/analysis.json` | Label distribution stats per mode (JSON) |
| `output/analysis.md` | Human-readable distribution summary |

## Final Result Schema

`results_merged.json` contains all original warning fields plus:

```json
{
  "llm_results": {
    "wuwl": { "llm_label": "FP", "llm_label_reason": "...", "mode_desc": "三分类+含算法标签" },
    "wuol": { "llm_label": "TP", "llm_label_reason": "...", "mode_desc": "三分类+不含算法标签" },
    "ouwl": { "llm_label": "FP", "llm_label_reason": "...", "mode_desc": "二分类+含算法标签" },
    "ouol": { "llm_label": "FP", "llm_label_reason": "...", "mode_desc": "二分类+不含算法标签" }
  }
}
```

Mode key legend: `wu`/`ou` = with/without Unknown class; `wl`/`ol` = with/without algorithm label.

## See Also

- `docs/design.md` — design decisions and prompt strategy
- `prompt.md` — original task specification

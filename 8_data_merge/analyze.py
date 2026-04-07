"""
Stage 8: Data Analysis
Analyzes the merged output files across CWE, TP/FP, project, and tool dimensions.
Reads:  output/merged_all.json
Writes: output/analysis.json, output/analysis.md
"""

import json
import os
from collections import Counter, defaultdict

INPUT_FILE = os.path.join("output", "merged_all.json")
OUT_JSON = os.path.join("output", "analysis.json")
OUT_MD = os.path.join("output", "analysis.md")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pct(n, total):
    return round(100 * n / total, 1) if total else 0


def counter_table_md(counter, title, col_name="Value", top_n=None):
    lines = [f"### {title}", ""]
    total = sum(counter.values())
    items = counter.most_common(top_n)
    lines.append(f"| {col_name} | Count | % |")
    lines.append("|---|---:|---:|")
    for k, v in items:
        lines.append(f"| {k} | {v} | {pct(v, total)}% |")
    lines.append(f"| **Total** | **{total}** | **100%** |")
    lines.append("")
    return "\n".join(lines)


def main():
    print(f"Loading {INPUT_FILE}...")
    data = load(INPUT_FILE)
    total = len(data)
    print(f"Total entries: {total}")

    # ── Determine final label ──────────────────────────────────────────────────
    # Use manual_annotation when available, else fall back to algorithm label
    def final_label(entry):
        m = entry.get("manual_annotation")
        if m and m not in (None, "", "Unknown"):
            return m
        return entry.get("label", "Unknown")

    # ── Aggregate counters ─────────────────────────────────────────────────────
    label_cnt = Counter()
    tool_cnt = Counter()
    project_cnt = Counter()
    cwe_cnt = Counter()

    label_by_tool = defaultdict(Counter)
    label_by_project = defaultdict(Counter)
    label_by_cwe = defaultdict(Counter)

    tool_project_cnt = defaultdict(Counter)

    for entry in data:
        lbl = final_label(entry)
        tool = entry.get("tool_name", "unknown")
        project = entry.get("project_name", "unknown")
        cwes = entry.get("cwe") or []

        label_cnt[lbl] += 1
        tool_cnt[tool] += 1
        project_cnt[project] += 1

        label_by_tool[tool][lbl] += 1
        label_by_project[project][lbl] += 1
        tool_project_cnt[tool][project] += 1

        for cwe in cwes:
            cwe_cnt[cwe] += 1
            label_by_cwe[cwe][lbl] += 1

    # ── Build JSON result ──────────────────────────────────────────────────────
    result = {
        "total": total,
        "by_label": dict(label_cnt),
        "by_tool": {t: dict(c) for t, c in label_by_tool.items()},
        "by_project": {p: dict(c) for p, c in label_by_project.items()},
        "by_cwe": {cwe: dict(c) for cwe, c in label_by_cwe.items()},
        "tool_project_matrix": {t: dict(c) for t, c in tool_project_cnt.items()},
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"Written {OUT_JSON}")

    # ── Build Markdown report ──────────────────────────────────────────────────
    md = [
        "# Stage 8: Merged Data Analysis",
        "",
        f"Total entries: **{total}**",
        "",
    ]

    # Overall label distribution
    md.append(counter_table_md(label_cnt, "Overall Label Distribution", "Label"))

    # By tool
    md.append("### Label Distribution by Tool\n")
    md.append("| Tool | TP | FP | Unknown | Total |")
    md.append("|---|---:|---:|---:|---:|")
    for tool in sorted(tool_cnt):
        c = label_by_tool[tool]
        t = sum(c.values())
        md.append(f"| {tool} | {c.get('TP',0)} | {c.get('FP',0)} | {c.get('Unknown',0)} | {t} |")
    md.append("")

    # By project
    md.append("### Label Distribution by Project\n")
    md.append("| Project | TP | FP | Unknown | Total |")
    md.append("|---|---:|---:|---:|---:|")
    for proj in sorted(project_cnt):
        c = label_by_project[proj]
        t = sum(c.values())
        md.append(f"| {proj} | {c.get('TP',0)} | {c.get('FP',0)} | {c.get('Unknown',0)} | {t} |")
    md.append("")

    # By CWE (top 20)
    md.append(counter_table_md(cwe_cnt, "Top 20 CWE Distribution", "CWE", top_n=20))

    # CWE TP rate (top 20 by total)
    md.append("### TP Rate by CWE (Top 20 by count)\n")
    md.append("| CWE | TP | FP | Unknown | Total | TP Rate |")
    md.append("|---|---:|---:|---:|---:|---:|")
    for cwe, _ in cwe_cnt.most_common(20):
        c = label_by_cwe[cwe]
        t = sum(c.values())
        tp = c.get("TP", 0)
        fp = c.get("FP", 0)
        unk = c.get("Unknown", 0)
        tp_rate = pct(tp, tp + fp) if (tp + fp) > 0 else 0
        md.append(f"| {cwe} | {tp} | {fp} | {unk} | {t} | {tp_rate}% |")
    md.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"Written {OUT_MD}")


if __name__ == "__main__":
    main()

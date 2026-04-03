"""
合并四种模式的 LLM 分类结果，并输出数据分析报告。

将四个独立结果文件合并为包含 llm_results 字段的最终数据集，
并统计各模式下 TP/FP/Unknown 的分布情况。

用法：
    python merge.py

输出：
    output/results_merged.json   最终合并结果
    output/analysis.json         分析统计（JSON）
    output/analysis.md           分析统计（Markdown 可读版）
"""

import json
import os
from collections import defaultdict, Counter

# ──────────────────────────────────────────────
# 模式配置：结果文件路径 → llm_results 中的键名与描述
# ──────────────────────────────────────────────
MODES = {
    "with_unknown_with_label": {
        "file":      "output/results_with_unknown_with_label.json",
        "key":       "wuwl",
        "mode_desc": "三分类+含算法标签",
    },
    "with_unknown_without_label": {
        "file":      "output/results_with_unknown_without_label.json",
        "key":       "wuol",
        "mode_desc": "三分类+不含算法标签",
    },
    "without_unknown_with_label": {
        "file":      "output/results_without_unknown_with_label.json",
        "key":       "ouwl",
        "mode_desc": "二分类+含算法标签",
    },
    "without_unknown_without_label": {
        "file":      "output/results_without_unknown_without_label.json",
        "key":       "ouol",
        "mode_desc": "二分类+不含算法标签",
    },
}

OUTPUT_MERGED   = "output/results_merged.json"
OUTPUT_ANALYSIS_JSON = "output/analysis.json"
OUTPUT_ANALYSIS_MD   = "output/analysis.md"

# LLM 结果中保留到 llm_results 的字段
LLM_FIELDS = {"llm_label", "llm_label_reason"}

# 合并结果中不重复携带的 LLM 专属字段（已被归入 llm_results）
EXCLUDE_TOP_LEVEL = {"llm_label", "llm_label_reason"}


def load_results(filepath: str) -> dict[int, dict]:
    """加载一个模式的结果文件，返回 {id: item} 字典。"""
    if not os.path.exists(filepath):
        print(f"  [跳过] 文件不存在：{filepath}")
        return {}
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    return {item["id"]: item for item in data if "id" in item}


def merge_results() -> list[dict]:
    """
    合并四种模式的结果。

    以任意一个模式文件中出现的 id 集合为基础，
    对每个 id 构造 llm_results 字典，保留原始警告字段。
    """
    # 加载所有模式数据
    mode_data: dict[str, dict[int, dict]] = {}
    all_ids: set[int] = set()
    for mode_name, cfg in MODES.items():
        data = load_results(cfg["file"])
        mode_data[mode_name] = data
        all_ids.update(data.keys())

    if not all_ids:
        print("错误：未找到任何结果文件，请先运行 llm.py 的四种模式。")
        return []

    print(f"共找到 {len(all_ids)} 个唯一 ID，开始合并...")

    merged = []
    for item_id in sorted(all_ids):
        # 取第一个有数据的模式作为基础字段来源
        base: dict = {}
        for mode_name in MODES:
            if item_id in mode_data[mode_name]:
                base = mode_data[mode_name][item_id]
                break

        # 构造顶层字段（去除 LLM 专属字段）
        entry = {k: v for k, v in base.items() if k not in EXCLUDE_TOP_LEVEL}

        # 构造 llm_results
        llm_results: dict[str, dict] = {}
        for mode_name, cfg in MODES.items():
            item = mode_data[mode_name].get(item_id)
            if item is None:
                continue
            llm_results[cfg["key"]] = {
                "llm_label":        item.get("llm_label"),
                "llm_label_reason": item.get("llm_label_reason"),
                "mode_desc":        cfg["mode_desc"],
            }

        entry["llm_results"] = llm_results
        merged.append(entry)

    return merged


def analyze(merged: list[dict]) -> dict:
    """计算各模式下标签分布及与算法标签的一致性统计。"""
    stats: dict = {}

    for mode_name, cfg in MODES.items():
        key = cfg["key"]
        label_counter: Counter = Counter()
        agreement_counter: Counter = Counter()  # llm_label vs label (算法标签)

        for entry in merged:
            lr = entry.get("llm_results", {}).get(key)
            if lr is None:
                continue
            llm_label = lr.get("llm_label")
            algo_label = entry.get("label")
            label_counter[llm_label] += 1
            if algo_label and llm_label:
                agreement_counter[f"{algo_label}→{llm_label}"] += 1

        stats[key] = {
            "mode_desc":   cfg["mode_desc"],
            "total":       sum(label_counter.values()),
            "distribution": dict(label_counter),
            "agreement":    dict(agreement_counter),
        }

    return stats


def write_analysis_md(stats: dict, merged: list[dict], filepath: str):
    lines = ["# Stage 6 LLM 分类结果分析\n"]
    lines.append(f"合并后总条目数：**{len(merged)}**\n")

    for key, s in stats.items():
        lines.append(f"\n## 模式：{key}（{s['mode_desc']}）\n")
        lines.append(f"有效结果数：{s['total']}\n")
        lines.append("\n### 标签分布\n")
        lines.append("| 标签 | 数量 | 占比 |\n|------|------|------|\n")
        total = s["total"] or 1
        for label, cnt in sorted(s["distribution"].items(), key=lambda x: -x[1]):
            lines.append(f"| {label} | {cnt} | {cnt/total:.1%} |\n")

        if s["agreement"]:
            lines.append("\n### 算法标签 vs LLM 标签（一致性）\n")
            lines.append("| 算法→LLM | 数量 |\n|----------|------|\n")
            for pair, cnt in sorted(s["agreement"].items(), key=lambda x: -x[1]):
                lines.append(f"| {pair} | {cnt} |\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main():
    os.makedirs("output", exist_ok=True)

    merged = merge_results()
    if not merged:
        return

    # 保存合并结果
    with open(OUTPUT_MERGED, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
    print(f"合并完成，共 {len(merged)} 条结果 → {OUTPUT_MERGED}")

    # 分析统计
    stats = analyze(merged)

    with open(OUTPUT_ANALYSIS_JSON, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"分析统计（JSON）→ {OUTPUT_ANALYSIS_JSON}")

    write_analysis_md(stats, merged, OUTPUT_ANALYSIS_MD)
    print(f"分析统计（Markdown）→ {OUTPUT_ANALYSIS_MD}")

    # 简要打印到控制台
    for key, s in stats.items():
        dist = s["distribution"]
        print(f"\n[{key}] {s['mode_desc']}  总计={s['total']}")
        for label, cnt in sorted(dist.items(), key=lambda x: -x[1]):
            print(f"    {label}: {cnt} ({cnt/(s['total'] or 1):.1%})")


if __name__ == "__main__":
    main()

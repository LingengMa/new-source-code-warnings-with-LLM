#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合并标注结果，生成最终完整数据集

将两类条目合并为单一输出文件：
  1. 标签一致条目（1513 条）：自动采用一致标签，注明无需人工审核
  2. 标签不一致条目（873 条）：采用人工标注结果（来自 annotations.json）

输入：
  input/results_merged.json   — Stage 6 的全量输出（含五套标签）
  annotations.json            — 人工标注工具写入的标注结果

输出：
  output/merged_annotated.json   — 最终完整数据集（全量，含 manual_annotation 等字段）
  output/merge_stats.json        — 合并统计摘要

用法（在 7_annotate/ 目录下运行）：
  python merge.py
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone

# ── 路径 ──────────────────────────────────────────────────────────────────────
BASE_DIR         = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE       = os.path.join(BASE_DIR, 'input', 'results_merged.json')
ANNOTATIONS_FILE = os.path.join(BASE_DIR, 'annotations.json')
OUTPUT_DIR       = os.path.join(BASE_DIR, 'output')
OUTPUT_FILE      = os.path.join(OUTPUT_DIR, 'merged_annotated.json')
STATS_FILE       = os.path.join(OUTPUT_DIR, 'merge_stats.json')

LLM_KEYS = ['wuwl', 'wuol', 'ouwl', 'ouol']

AUTO_REASON = (
    '所有标签（算法标签及四种LLM标签）完全一致，'
    '无需人工审核，自动采用一致标签。'
)

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def collect_labels(entry: dict) -> list[str]:
    """收集一条告警的所有非空标签值（算法标签 + 四种 LLM 标签）。"""
    labels: list[str] = []
    algo = entry.get('label')
    if algo:
        labels.append(algo)
    for key in LLM_KEYS:
        result = (entry.get('llm_results') or {}).get(key)
        if result:
            lbl = result.get('llm_label')
            if lbl:
                labels.append(lbl)
    return labels


def is_consistent(entry: dict) -> bool:
    return len(set(collect_labels(entry))) <= 1


def consistent_label(entry: dict) -> str | None:
    labels = collect_labels(entry)
    return labels[0] if labels else None


# ── 主逻辑 ───────────────────────────────────────────────────────────────────

def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        all_data: list[dict] = json.load(f)

    with open(ANNOTATIONS_FILE, 'r', encoding='utf-8') as f:
        annotations: dict[str, dict] = json.load(f)

    now_iso = datetime.now(tz=timezone.utc).isoformat()

    merged: list[dict] = []
    stats = {
        'total': len(all_data),
        'consistent_auto_annotated': 0,
        'inconsistent_manual_annotated': 0,
        'inconsistent_missing_annotation': 0,
        'label_distribution': Counter(),
    }

    for entry in all_data:
        rec = entry.copy()
        wid = str(entry['id'])

        if is_consistent(entry):
            lbl = consistent_label(entry)
            rec['manual_annotation']   = lbl
            rec['annotation_reason']   = AUTO_REASON
            rec['annotation_timestamp'] = now_iso
            stats['consistent_auto_annotated'] += 1
            if lbl:
                stats['label_distribution'][lbl] += 1

        else:
            ann = annotations.get(wid)
            if ann:
                rec['manual_annotation']   = ann['label']
                rec['annotation_reason']   = ann.get('reason', '')
                rec['annotation_timestamp'] = ann.get('timestamp', now_iso)
                stats['inconsistent_manual_annotated'] += 1
                stats['label_distribution'][ann['label']] += 1
            else:
                rec['manual_annotation']   = None
                rec['annotation_reason']   = None
                rec['annotation_timestamp'] = None
                stats['inconsistent_missing_annotation'] += 1

        merged.append(rec)

    stats['label_distribution'] = dict(stats['label_distribution'])

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f'总条目数:              {stats["total"]}')
    print(f'一致（自动标注）:       {stats["consistent_auto_annotated"]}')
    print(f'不一致（人工标注）:     {stats["inconsistent_manual_annotated"]}')
    print(f'不一致（缺少标注）:     {stats["inconsistent_missing_annotation"]}')
    print(f'标签分布:              {stats["label_distribution"]}')
    print(f'\n输出文件: {OUTPUT_FILE}')
    print(f'统计文件: {STATS_FILE}')


if __name__ == '__main__':
    main()

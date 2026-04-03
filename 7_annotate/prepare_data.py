#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
准备人工标注数据集

从 input/results_merged.json 中分离出五套标签不完全一致的条目，
写入 data.json 供 src/app.py 使用。

五套标签：
  1. label        — 算法追踪标签（TP/FP/Unknown）
  2. wuwl         — 三分类 + 含算法标签
  3. wuol         — 三分类 + 不含算法标签
  4. ouwl         — 二分类 + 含算法标签
  5. ouol         — 二分类 + 不含算法标签

"不完全一致"定义：五套标签中至少有两个不相同。

用法（在 7_annotate/ 目录下运行）：
    python prepare_data.py

输出：
    data.json         需要人工标注的条目（标签不一致）
    output/stats.json 统计摘要
"""

import json
import os
from collections import Counter

# ── 路径 ──────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, 'input', 'results_merged.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
DATA_FILE  = os.path.join(BASE_DIR, 'data.json')
STATS_FILE = os.path.join(OUTPUT_DIR, 'prepare_stats.json')

LLM_KEYS = ['wuwl', 'wuol', 'ouwl', 'ouol']


def collect_labels(entry: dict) -> list[str]:
    """收集一条告警的所有非空标签值。"""
    labels = []
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


def is_inconsistent(entry: dict) -> bool:
    """若五套标签中至少有两个不同，则需要人工标注。"""
    labels = collect_labels(entry)
    return len(set(labels)) > 1


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        all_data = json.load(f)

    total = len(all_data)
    inconsistent = [e for e in all_data if is_inconsistent(e)]
    consistent   = [e for e in all_data if not is_inconsistent(e)]

    # 统计不一致条目中各标签的分布
    label_dist: Counter = Counter()
    for entry in inconsistent:
        for lbl in set(collect_labels(entry)):
            label_dist[lbl] += 1

    stats = {
        'total': total,
        'consistent': len(consistent),
        'inconsistent': len(inconsistent),
        'inconsistent_label_distribution': dict(label_dist),
    }

    # 写出 data.json（供 app.py 读取）
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(inconsistent, f, indent=2, ensure_ascii=False)

    # 写出统计摘要
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)

    print(f'总条目数:         {total}')
    print(f'标签一致（跳过）: {len(consistent)}')
    print(f'标签不一致（待标注）: {len(inconsistent)}')
    print(f'标签分布（不一致集合）: {dict(label_dist)}')
    print(f'\n数据文件: {DATA_FILE}')
    print(f'统计文件: {STATS_FILE}')


if __name__ == '__main__':
    main()

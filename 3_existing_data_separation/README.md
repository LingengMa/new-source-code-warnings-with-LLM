# 3_existing_data_separation — 已处理数据分离

从 `data_all_labeled.json` 中分离出已完成处理的告警，仅保留尚未处理的条目，避免对已完成数据重复执行后续高成本任务。

## 环境安装

本阶段仅使用 Python 标准库，无需额外依赖。

```bash
conda create -n separator python=3.11 -y
# 无需安装其他包
```

## 使用方法

```bash
# 在 3_existing_data_separation 目录下执行
python separate.py
```

## 输入 / 输出

| 路径 | 说明 |
|------|------|
| `input/data_all_labeled.json` | 上一阶段（2_algorithm_match）产出的带标签告警列表 |
| `input/llm_results_with_annotated_data_2510.json` | 已完成处理（LLM 匹配 + 人工标注）的告警数据集 |
| `output/data_remaining.json` | 尚未处理的告警（不在已有数据集中的条目） |
| `output/stats.json` | 分离统计信息（总数、已跳过、剩余数量） |

## 存在性判定规则

两条告警被视为相同，当且仅当以下四个字段全部一致：

```
tool_name + project_name_with_version + file_path + line_number
```


# Stage 7: 人工标注 (Manual Annotation)

本阶段对标签不一致的静态分析告警进行人工标注，输出最终数据集。

## 数据流

```
input/results_merged.json   ← 来自 6_llm_match/output/results_merged.json
        ↓
  prepare_data.py
        ↓
   data.json（根目录）        ← 五套标签不完全一致的告警子集（873 条）
        ↓
  src/app.py（Flask Web）
        ↓
  annotations.json（根目录）  ← 人工标注结果（key=id）
        ↓
  merge.py
        ↓
  output/merged_annotated.json  ← 最终完整数据集（2386 条，含一致 + 人工标注）
```

### 五套标签

| 字段 | 来源 |
|------|------|
| `label` | 算法追踪（Stage 2）|
| `llm_results.wuwl.llm_label` | LLM 三分类 + 含算法标签 |
| `llm_results.wuol.llm_label` | LLM 三分类 + 不含算法标签 |
| `llm_results.ouwl.llm_label` | LLM 二分类 + 含算法标签 |
| `llm_results.ouol.llm_label` | LLM 二分类 + 不含算法标签 |

五套标签中**至少有两个不同**的条目需要人工标注。

## 运行

### 1. 环境准备

```bash
conda create -n annotate python=3.11 -y
conda run -n annotate pip install -r src/requirements.txt
```

### 2. 准备数据

```bash
cd 7_annotate
conda run -n annotate python prepare_data.py
# 输出: data.json（根目录）, output/prepare_stats.json
```

### 3. 启动标注 Web 服务

```bash
cd 7_annotate/src
conda activate annotate
python app.py
# 访问: http://localhost:5000
```

> 源文件浏览功能需要 `input/repository/` 目录下有对应的代码仓库（软链接或目录）。

### 4. 合并最终数据集

人工标注完成后，运行以下命令将人工标注结果与一致条目合并为完整数据集：

```bash
cd 7_annotate
conda run -n annotate python merge.py
# 输出: output/merged_annotated.json（全量，2386 条）, output/merge_stats.json
```

合并规则：

| 条目类型 | 标注来源 | annotation_reason |
|----------|----------|-------------------|
| 五套标签完全一致（1513 条）| 自动采用一致标签 | "所有标签…完全一致，无需人工审核，自动采用一致标签。" |
| 五套标签不完全一致（873 条）| 来自 `annotations.json`（人工标注）| 人工填写的理由 |

## 文件结构

```
7_annotate/
├── prepare_data.py          # 分离待标注子集 → data.json
├── merge.py                 # 合并标注结果 → output/merged_annotated.json
├── data.json                # 运行 prepare_data.py 后生成
├── annotations.json         # 标注工具写入的标注结果
├── input/
│   ├── results_merged.json  # Stage 6 merge.py 的输出（含五套标签）
│   └── repository/          # 各项目源代码（用于源文件查看）
├── output/
│   ├── prepare_stats.json   # prepare_data.py 的统计摘要
│   ├── merged_annotated.json  # merge.py 的最终完整数据集（全量）
│   └── merge_stats.json     # merge.py 的合并统计摘要
└── src/
    ├── app.py               # Flask Web 标注服务
    ├── requirements.txt     # Flask==3.0.0, Flask-CORS==4.0.0
    └── templates/
        └── index.html       # 标注 UI
```

## 标注工具使用

- **左侧列表**：显示所有待标注条目，支持搜索（ID / 工具 / 文件 / 消息）
- **详情面板**：显示告警元信息、五套标签对比、代码切片
- **标注操作**：点击按钮或使用快捷键

| 快捷键 | 操作 |
|--------|------|
| `T` | 标注为 TP |
| `F` | 标注为 FP |
| `U` | 标注为 Unknown |
| `A` | 上一条 |
| `D` | 下一条 |
| `N` | 下一个未标注 |
| `Delete` | 删除当前标注 |
| `Esc` | 关闭源文件弹窗 |

- **导出**：点击顶栏"导出"按钮下载含标注结果的完整 JSON

## 注意事项

- `data.json` 和 `annotations.json` 在 `.gitignore` 中（数据文件，不应提交）
- 若 `input/` 数据有问题，应从上一阶段（`6_llm_match`）查找并修复，而非在本阶段适配
- 每次程序变更后同步更新本文档

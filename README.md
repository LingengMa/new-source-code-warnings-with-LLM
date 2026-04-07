# 静态分析警告数据集构建流程

本仓库是一个面向漏洞研究的数据集自动化构建流水线，针对 10 个开源 C 项目的多个版本，收集 4 种静态分析工具的输出警告，经过算法标注、数据筛选、代码切片、大模型分类和人工标注等多个阶段，最终产出高质量的带标签警告数据集。

---

## 项目概况

| 维度 | 内容 |
|------|------|
| 目标语言 | C |
| 静态分析工具 | CodeQL、Cppcheck、CSA（Clang Static Analyzer）、Semgrep |
| 覆盖项目 | curl、ffmpeg、git、libuv、musl、nginx、openssl、redis、tmux、vim |
| 每项目版本数 | 6 个版本（共 60 个项目版本实例） |
| 最终数据规模 | **4896 条警告**，全部附带代码切片与多模式大模型分类结果 |

---

## 流水线总览

```
原始工具输出
    │
    ▼
[1] 警告提取        →  data_all.json            （全量警告，统一 Schema）
    │
    ▼
[2] 算法标注        →  data_all_labeled.json     （TP / FP / Unknown）
    │
    ▼
[3] 存量数据分离    →  data_remaining.json       （去除已处理批次）
    │
    ▼
[4] 数据准备
    ├─ [4_1] CWE 补全   →  data_remaining_cwe_supplement.json
    └─ [4_2] 数据过滤   →  data_filtered.json    （2386 条）
    │
    ▼
[5] 代码切片        →  slices_for_llm_with_label.json
    │
    ▼
[6] 大模型分类      →  results_merged.json       （4 种模式×2386 条）
    │
    ▼
[7] 人工标注        →  annotations.json          （标注不一致条目）
    │
    ▼
[8] 数据合并        →  merged_all.json (4896)
                       merged_annotated.json (1898)
```

---

## 各阶段详细说明

### 阶段 1：警告提取（`1_extractor/`）

从原始工具报告中解析所有警告，统一为标准 Schema。

**输入：** `input/data/<tool>/<project>/` 下的原始报告

| 工具 | 格式 |
|------|------|
| CodeQL | `.sarif`（JSON 格式） |
| Cppcheck | `.xml` |
| CSA | HTML（index.html + 各报告页） |
| Semgrep | `.json` |

**输出：** `output/data_all.json`

**统一 Schema：**
```json
{
  "tool_name": "semgrep|codeql|cppcheck|csa",
  "project_name": "curl",
  "project_name_with_version": "curl-8_11_1",
  "project_version": "8.11.1",
  "file_path": "src/foo.c",
  "line_number": 42,
  "cwe": ["CWE-20"],
  "rule_id": "...",
  "message": "...",
  "severity": "WARNING|ERROR|..."
}
```

**路径命名规则（关键）：** curl 的 `project_name_with_version` 使用下划线（如 `curl-8_11_1`），其余项目使用点分格式（如 `ffmpeg-7.1.1`）。

---

### 阶段 2：算法标注（`2_algorithm_match/`）

基于警告在多个版本中的生命周期，通过版本对比算法为每条警告赋予标签。

**标注逻辑：**
- **FP（假阳性）**：在后续版本中仍能匹配到同一条警告 → 警告持续存在，可能是误报
- **TP（真阳性）**：在所有后续版本中均无法匹配 → 警告消失，推测已被修复
- **Unknown**：仅出现在最新版本，无法比较

**匹配策略（4 级递进）：** 精确匹配 → 位置匹配 → 代码片段匹配 → 哈希匹配

**输出：** `output/data_all_labeled.json`（在 Schema 基础上增加 `label` 字段和 UUID `id`）

---

### 阶段 3：存量数据分离（`3_existing_data_separation/`）

将上一批次已处理的警告从总数据中剔除，得到本批次待处理的增量数据。

**身份标识键：** `tool_name + project_name_with_version + file_path + line_number`

**输出：** `output/data_remaining.json`、`output/stats.json`

---

### 阶段 4：数据准备（`4_data_prepare/`）

#### 4_1：CWE 补全（`4_1_cwe_supplement/`）

为 `cwe` 字段为空的条目，根据 `rule_id` 查询工具专属映射表进行填充。CWE 值**只补充、不覆盖**，格式为 `["CWE-NNN"]`。

| 工具 | 映射源 | 覆盖率 |
|------|--------|--------|
| CodeQL | `cwe_information/codeql/merged_codeql_C_report.json` | 100% |
| Cppcheck | `cwe_information/merged_cppcheck_report.json` | 部分（诊断类规则无 CWE） |
| CSA | `cwe_information/csa_merged_cwe.json` | 100% |
| Semgrep | — | 原始数据已完整 |

**输出：** `output/data_remaining_cwe_supplement.json`

#### 4_2：数据过滤（`4_2_data_filter/`）

按顺序应用以下四项过滤规则：

| 步骤 | 规则 | 过滤前 | 过滤后 | 去除数 |
|------|------|--------|--------|--------|
| 1 | 保留 CWE Top25 交集（同时去除空 CWE） | 430,496 | 3,245 | 427,251 |
| 2 | 去除测试文件中的警告 | 3,245 | 3,140 | 105 |
| 3 | 去除 `#define` 行警告 | 3,140 | 3,140 | 0 |
| 4 | 去除最新版本的警告（无后续版本可比较） | 3,140 | 2,386 | 754 |

**输出：** `output/data_filtered.json`（**2386 条**）

---

### 阶段 5：代码切片（`5_slice/slice_joern/`）

调用 [Joern](https://joern.io)（安装于 `/opt/joern-cli`）对每条警告所在函数构建 PDG（程序依赖图），进行前向/后向切片，提取与该警告相关的代码片段。

**处理流程：**
1. `JoernAnalyzer` 调用 `joern-parse` + `joern-export` 导出 DOT 格式 PDG
2. `pdg_loader.py` 解析 PDG 为图对象
3. `slice_engine.py` 执行双向切片（默认深度各 10 层）
4. `ast_enhancer.py` 用 tree-sitter 修复切片语法完整性（括号、if-else 配对）
5. `code_extractor.py` 组装切片字符串，省略行用 `PLACEHOLDER` 注释占位，并附上被调用函数定义

**输出扩展字段：**
```json
{
  "slice_code": "...",
  "slice_lines": [1, 5, 7],
  "function_name": "curl_easy_setopt",
  "function_definitions": { "helper_fn": "..." }
}
```

**支持断点续跑**（`output/checkpoint.json`），默认 5 个并行进程。

**输出：** `output/slices_for_llm_with_label.json`

---

### 阶段 6：大模型分类（`6_llm_match/`）

调用 DeepSeek API（`deepseek-chat` 模型，JSON Output 模式）对每条带切片的警告进行 TP/FP 分类，共运行 4 种模式：

| 模式代码 | 分类类别 | 是否包含算法标签 |
|----------|----------|-----------------|
| `wuwl` | TP / FP / Unknown（三分类） | 是 |
| `wuol` | TP / FP / Unknown（三分类） | 否 |
| `ouwl` | TP / FP（二分类） | 是 |
| `ouol` | TP / FP（二分类） | 否 |

各模式分类结果统计（新批次 2386 条）：

| 模式 | TP | FP | Unknown |
|------|----|----|---------|
| wuwl（三分类+含标签） | 56 (2.3%) | 2193 (91.9%) | 137 (5.7%) |
| wuol（三分类+不含标签） | 165 (6.9%) | 1693 (71.0%) | 528 (22.1%) |
| ouwl（二分类+含标签） | 27 (1.1%) | 2359 (98.9%) | — |
| ouol（二分类+不含标签） | 189 (7.9%) | 2197 (92.1%) | — |

**支持断点续跑**（按 id 跳过已处理条目）。全部运行后执行 `python merge.py` 合并为 `results_merged.json`。

**输出：** `output/results_merged.json`（每条附 `llm_results` 字段，含 4 个模式结果及中文推理说明）

---

### 阶段 7：人工标注（`7_annotate/`）

对算法标签与任意一个大模型标签不一致的条目进行人工复核。提供基于 Flask 的 Web 标注界面。

**不一致标准：** `label`（算法）与 `llm_results` 中任意一个 `llm_label` 不同。

**运行方式：**
```bash
cd 7_annotate
conda run -n annotate python prepare_data.py  # 生成待标注子集 data.json
cd src && python app.py                        # 启动标注界面 → http://localhost:5000
```

**新批次标注量：** 873 条（占 2386 条的 36.6%）

---

### 阶段 8：数据合并（`8_data_merge/`）

将旧批次（2510 条）和新批次（2386 条）合并为完整数据集，并重新分配 ID。

**ID 分配规则：**
- 旧批次保留原 ID（1–2510）不变
- 新批次从 ID 2511 开始顺序分配

**最终标签优先级：** `manual_annotation`（人工标注，非空时优先）> `label`（算法标注）

**运行：**
```bash
cd 8_data_merge
python merge.py    # → output/merged_all.json (4896), merged_annotated.json (1898)
python analyze.py  # → output/analysis.json, output/analysis.md
```

---

## 最终数据集（`finally_dataset/`）

### 文件清单

| 文件 | 批次 | 说明 | 条目数 |
|------|------|------|--------|
| `previous/llm_results_with_annotated_data_2510.json` | 旧批次 | 全量数据 | 2510 |
| `previous/llm_results_with_annotated_data_1025.json` | 旧批次 | 人工标注的不一致条目 | 1025 |
| `now/llm_results_with_annotated_data_2386.json` | 新批次 | 全量数据 | 2386 |
| `now/llm_results_with_annotated_data_873.json` | 新批次 | 人工标注的不一致条目 | 873 |
| `all/llm_results_with_annotated_data_4896.json` | 合并 | **完整数据集** | **4896** |
| `all/llm_results_with_annotated_data_1898.json` | 合并 | 所有人工标注条目 | 1898 |

### 数据字段说明

每条数据包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | int | 数据集内唯一 ID（1–4896） |
| `tool_name` | str | 静态分析工具名称 |
| `project_name` | str | 项目名称 |
| `project_name_with_version` | str | 项目名+版本（即仓库目录名） |
| `project_version` | str | 版本号 |
| `file_path` | str | 警告所在文件（相对路径） |
| `line_number` | int | 警告行号 |
| `cwe` | list[str] | CWE 编号列表，如 `["CWE-476"]` |
| `rule_id` | str | 工具规则 ID |
| `message` | str | 工具原始警告信息 |
| `severity` | str | 严重级别 |
| `function_name` | str | 警告所在函数名 |
| `label` | str | 算法标注标签（`TP`/`FP`/`Unknown`） |
| `llm_results` | dict | 4 种大模型分类结果（含推理说明） |
| `sliced_code` | str | PDG 切片提取的相关代码片段 |
| `manual_annotation` | str\|null | 人工标注标签（`TP`/`FP`，不一致条目才有） |
| `annotation_reason` | str\|null | 人工标注理由 |
| `annotation_timestamp` | str\|null | 人工标注时间戳 |

### 标签分布

**总体（4896 条）：**

| 标签 | 数量 | 占比 |
|------|------|------|
| FP（假阳性） | 4561 | 93.2% |
| TP（真阳性） | 335 | 6.8% |

**按工具：**

| 工具 | TP | FP | 合计 |
|------|----|----|------|
| CodeQL | 179 | 1241 | 1420 |
| Cppcheck | 40 | 1237 | 1277 |
| CSA | 113 | 1902 | 2015 |
| Semgrep | 3 | 181 | 184 |

**按项目：**

| 项目 | TP | FP | 合计 |
|------|----|----|------|
| vim | 201 | 1091 | 1292 |
| git | 39 | 1200 | 1239 |
| ffmpeg | 35 | 649 | 684 |
| curl | 4 | 440 | 444 |
| openssl | 15 | 392 | 407 |
| redis | 22 | 274 | 296 |
| musl | 11 | 195 | 206 |
| tmux | 6 | 193 | 199 |
| nginx | 0 | 117 | 117 |
| libuv | 2 | 10 | 12 |

**CWE 分布（Top 5）：**

| CWE | 描述 | 条目数 | 占比 | TP 率 |
|-----|------|--------|------|-------|
| CWE-476 | NULL 指针解引用 | 3531 | 50.3% | 5.8% |
| CWE-120 | 缓冲区复制（越界检查不足） | 927 | 13.2% | 12.9% |
| CWE-787 | 越界写 | 878 | 12.5% | 13.8% |
| CWE-805 | 缓冲区访问（长度值不正确） | 823 | 11.7% | 14.2% |
| CWE-20 | 输入验证不当 | 155 | 2.2% | 0.0% |

---

## 资源位置

| 路径 | 说明 |
|------|------|
| `public/repository/` | 所有项目版本源代码（供切片提取使用） |
| `public/annotations_raw/data/` | 原始工具报告归档 |
| `1_extractor/input/repository/` | 阶段 1 使用的源码（软链接） |
| `1_extractor/input/data/项目版本.xlsx` | 项目版本列表电子表格 |
| `utils/cwe-information/` | CWE 映射表（XLSX → JSON 转换工具） |


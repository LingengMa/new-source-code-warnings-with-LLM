# 2_algorithm_match — 告警生命周期匹配与标注

对 `input/data_all.json` 中的静态分析告警进行跨版本匹配，依据告警在后续版本中的存活情况，将每条告警标注为 **TP**（真实修复）、**FP**（持续存在/误报）或 **Unknown**（最新版本无法判断）。

## 环境安装

```bash
conda create -n matcher python=3.11 -y
conda activate matcher
pip install -r requirements.txt
```

## 使用方法

```bash
# 在 2_algorithm_match 目录下执行
python tracker.py
```

输出：`output/data_all_labeled.json`

## 输入 / 输出

| 路径 | 说明 |
|------|------|
| `input/data_all.json` | 上一阶段（1_extractor）产出的统一格式告警列表 |
| `input/repository/` | 各项目各版本源码目录（用于代码内容匹配） |
| `output/data_all_labeled.json` | 在原字段基础上新增 `id`（UUID）与 `label` 字段 |

## 标注逻辑

| 标签 | 含义 |
|------|------|
| `TP` | 告警出现后在所有后续版本中消失，推断为已修复的真实问题 |
| `FP` | 告警在至少一个后续版本中仍能匹配到，推断为误报或持续存在的问题 |
| `Unknown` | 告警出现在该项目的最新版本，无后续版本可比较 |

## 匹配算法

见 `docs/DESIGN.md`。`match.py` 中的 `Matcher` 类实现了四层渐进式匹配（优先级从高到低）：

1. **精确匹配** — 相同文件路径 + 相同行号
2. **位置匹配** — 基于 diff 的相对位置（容忍行号偏移 ≤ 3 行）
3. **片段匹配** — 上下文代码片段相似度（默认阈值 0.8）
4. **哈希匹配** — 代码行首/尾 token 哈希（容忍变量重命名）

## 文档

| 文件 | 说明 |
|------|------|
| `docs/DESIGN.md` | 算法设计与数据流详细说明 |
| `docs/environment.md` | 环境配置说明 |

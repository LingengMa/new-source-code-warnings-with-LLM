# 1_extractor — 静态分析警告提取器

从四个静态分析工具（CodeQL、Cppcheck、CSA、Semgrep）的原始输出中提取警告，统一格式后写入 JSON 文件，并生成数据统计报告。

## 环境安装

```bash
conda create -n extractor python=3.11 -y
conda run -n extractor pip install beautifulsoup4 lxml
```

## 使用方法

```bash
# 1. 提取所有警告 → output/data_all.json
conda run -n extractor python extract.py

# 2. 统计分析 → output/analysis.md
conda run -n extractor python analyze.py
```

## 输入数据

| 路径 | 内容 |
|------|------|
| `input/data/codeql/<project>/` | CodeQL SARIF 文件（`.sarif`） |
| `input/data/cppcheck/<project>/` | Cppcheck XML 文件（`.xml`） |
| `input/data/csa/<project>/` | CSA HTML 报告目录，每版本含 `index.html` |
| `input/data/semgrep/<project>/` | Semgrep JSON 文件（`.json`） |
| `input/repository/` | 各项目源码（用于路径对齐参考） |
| `input/sample.json` | 统一警告格式示例 |

涉及项目：curl、ffmpeg、git、libuv、musl、nginx、openssl、redis、tmux、vim

## 输出格式

`output/data_all.json` — 警告列表，每条警告字段如下：

| 字段 | 类型 | 说明 |
|------|------|------|
| `tool_name` | string | 工具名：`codeql`/`cppcheck`/`csa`/`semgrep` |
| `project_name` | string | 项目名，如 `curl` |
| `project_name_with_version` | string | 下划线格式，如 `curl-8_7_1` |
| `project_version` | string | 点格式版本号，如 `8.7.1` |
| `file_path` | string | 相对于项目根的文件路径（CSA 仅为文件名） |
| `line_number` | int | 警告所在行号 |
| `cwe` | list[string] | CWE 编号列表，如 `["CWE-401"]`，无则为 `[]` |
| `rule_id` | string | 工具规则 ID |
| `message` | string | 警告描述 |
| `severity` | string | 严重程度，如 `WARNING`/`ERROR`/`NOTE` |

`output/analysis.md` — Markdown 格式统计报告，含各工具、项目、版本、CWE 维度的数量分布。

## 注意事项

- `project_name_with_version` 使用下划线格式以对齐 `input/repository/` 中的目录名，方便后续切片阶段从源码中提取代码片段。
- CSA 的 `file_path` 字段仅为文件名（非完整相对路径），因为 HTML 报告不提供完整路径信息。
- CSA 不提供 CWE 信息，`cwe` 字段恒为空列表。
- 空目录表示该工具在该项目/版本下未检测到任何警告（正常情况）。

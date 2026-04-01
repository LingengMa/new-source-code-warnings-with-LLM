# 各工具原始数据格式说明

本文档说明 `input/data/` 下四个静态分析工具的原始输出格式，以及 `extract.py` 的提取逻辑。

---

## CodeQL（SARIF JSON）

**文件格式**：`<project>-<version>_codeql.sarif`（标准 SARIF 2.1.0）

**提取路径**：

```
runs[0]
  .tool.driver.rules[]      → 规则元数据（含 CWE、严重级别）
  .results[]                → 警告实例
    .ruleId                 → rule_id
    .message.text           → message
    .locations[0]
      .physicalLocation
        .artifactLocation.uri    → file_path（已相对于 srcroot，无需处理）
        .region.startLine        → line_number
```

**CWE 提取**：规则的 `properties.tags` 数组中以 `external/cwe/cwe-NNN` 格式标注，提取为 `CWE-NNN`。

**Severity**：从 `rules[].defaultConfiguration.level` 获取（`note`/`warning`/`error`），转为大写。

---

## Cppcheck（XML）

**文件格式**：`<project>-<version>.xml`（Cppcheck XML 格式版本 2）

**提取路径**：

```xml
<results>
  <errors>
    <error id="..." severity="..." msg="..." cwe="...">
      <location file="..." line="..." column="..."/>
    </error>
```

**CWE 提取**：`error.cwe` 属性为可选纯数字（如 `"401"`），转为 `["CWE-401"]`。

**路径处理**：`location.file` 为绝对路径（如 `/mnt/c/.../curl-curl-8_7_1/src/foo.c`），通过找到路径中包含项目名的目录段截取后续相对路径。

---

## CSA / Clang Static Analyzer（HTML）

**文件格式**：每个版本在单独目录 `<project>-<version>/`，入口为 `index.html`（scan-build 生成）。

**提取方式**：解析 `index.html` 中 `<table class="sortable">` 的 `<tr class="bt_*">` 行：

| 列索引 | 内容 | 映射字段 |
|--------|------|----------|
| 0 | Bug Group（如 "Logic error"） | message 前缀 |
| 1 | Bug Type（如 "Dereference of null pointer"） | rule_id |
| 2 | 文件名（仅文件名，非完整路径） | file_path |
| 3 | 函数名 | （忽略） |
| 4 | 行号 | line_number |

**特殊情况**：FFmpeg 的 CSA 目录命名为 `FFmpeg-n<version>`（如 `FFmpeg-n6.0`），提取时统一转为小写项目名（`ffmpeg`）并去掉 `n` 前缀。

**限制**：
- HTML 只提供文件名，无完整路径，`file_path` 仅为文件名。
- HTML 不提供 CWE 信息，`cwe` 恒为 `[]`。
- Severity 统一设为 `WARNING`。

---

## Semgrep（JSON）

**文件格式**：`<project>-<version>_semgrep.json`

**提取路径**：

```
results[]
  .check_id          → rule_id
  .path              → file_path（绝对路径，需截取）
  .start.line        → line_number
  .extra
    .message         → message
    .severity        → severity
    .metadata.cwe[]  → cwe（格式 "CWE-NNN: Description"，提取 "CWE-NNN" 部分）
```

**路径处理**：同 Cppcheck，`path` 为绝对路径，截取项目根后的相对路径。

|                        File                        | Old  | New  | Consistent Data | Annotation Data |
| :------------------------------------------------: | :--: | :--: | :-------------: | :-------------: |
| previous/llm_results_with_annotated_data_1025.json |  ✅   |      |                 |        ✅        |
| previous/llm_results_with_annotated_data_2510.json |  ✅   |      |        ✅        |        ✅        |
|    now/llm_results_with_annotated_data_873.json    |      |  ✅   |                 |        ✅        |
|   now/llm_results_with_annotated_data_2386.json    |      |  ✅   |        ✅        |        ✅        |
|   all/llm_results_with_annotated_data_1898.json    |  ✅   |  ✅   |                 |        ✅        |
|   all/llm_results_with_annotated_data_4896.json    |  ✅   |  ✅   |        ✅        |        ✅        |

该表格记录了不同的数据分布, 包括

- 增量数据标注(单独分析的新数据 `Old`)
- 存量数据 (先前项目完成的数据标注 `New`)
- 大模型标注和算法标注一致通过的数据 (无需人工标注 `Consistent Data`)
- 大模型标注和算法标注不一致的数据 (需要人工标注 `Annotation Data`)



### 数据字段说明

每条数据包含以下字段：

| 字段                        | 类型      | 说明                                      |
| --------------------------- | --------- | ----------------------------------------- |
| `id`                        | int       | 数据集内唯一 ID（1–4896）                 |
| `tool_name`                 | str       | 静态分析工具名称                          |
| `project_name`              | str       | 项目名称                                  |
| `project_name_with_version` | str       | 项目名+版本（即仓库目录名）               |
| `project_version`           | str       | 版本号                                    |
| `file_path`                 | str       | 警告所在文件（相对路径）                  |
| `line_number`               | int       | 警告行号                                  |
| `cwe`                       | list[str] | CWE 编号列表，如 `["CWE-476"]`            |
| `rule_id`                   | str       | 工具规则 ID                               |
| `message`                   | str       | 工具原始警告信息                          |
| `severity`                  | str       | 严重级别                                  |
| `function_name`             | str       | 警告所在函数名                            |
| `label`                     | str       | 算法标注标签（`TP`/`FP`/`Unknown`）       |
| `llm_results`               | dict      | 4 种大模型分类结果（含推理说明）          |
| `sliced_code`               | str       | PDG 切片提取的相关代码片段                |
| `manual_annotation`         | str\|null | 人工标注标签（`TP`/`FP`，不一致条目才有） |
| `annotation_reason`         | str\|null | 人工标注理由                              |
| `annotation_timestamp`      | str\|null | 人工标注时间戳                            |

## 算法标注逻辑

| 标签      | 含义                                                         |
| --------- | ------------------------------------------------------------ |
| `TP`      | 告警出现后在所有后续版本中消失，推断为已修复的真实问题       |
| `FP`      | 告警在至少一个后续版本中仍能匹配到，推断为误报或持续存在的问题 |
| `Unknown` | 告警出现在该项目的最新版本，无后续版本可比较                 |



### 标签分布

**总体（4896 条）：**

| 标签         | 数量 | 占比  |
| ------------ | ---- | ----- |
| FP（假阳性） | 4561 | 93.2% |
| TP（真阳性） | 335  | 6.8%  |

**按工具：**

| 工具     | TP   | FP   | 合计 |
| -------- | ---- | ---- | ---- |
| CodeQL   | 179  | 1241 | 1420 |
| Cppcheck | 40   | 1237 | 1277 |
| CSA      | 113  | 1902 | 2015 |
| Semgrep  | 3    | 181  | 184  |

**按项目：**

| 项目    | TP   | FP   | 合计 |
| ------- | ---- | ---- | ---- |
| vim     | 201  | 1091 | 1292 |
| git     | 39   | 1200 | 1239 |
| ffmpeg  | 35   | 649  | 684  |
| curl    | 4    | 440  | 444  |
| openssl | 15   | 392  | 407  |
| redis   | 22   | 274  | 296  |
| musl    | 11   | 195  | 206  |
| tmux    | 6    | 193  | 199  |
| nginx   | 0    | 117  | 117  |
| libuv   | 2    | 10   | 12   |

**CWE 分布（Top 5）：**

| CWE     | 描述                       | 条目数 | 占比  | TP 率 |
| ------- | -------------------------- | ------ | ----- | ----- |
| CWE-476 | NULL 指针解引用            | 3531   | 50.3% | 5.8%  |
| CWE-120 | 缓冲区复制（越界检查不足） | 927    | 13.2% | 12.9% |
| CWE-787 | 越界写                     | 878    | 12.5% | 13.8% |
| CWE-805 | 缓冲区访问（长度值不正确） | 823    | 11.7% | 14.2% |
| CWE-20  | 输入验证不当               | 155    | 2.2%  | 0.0%  |

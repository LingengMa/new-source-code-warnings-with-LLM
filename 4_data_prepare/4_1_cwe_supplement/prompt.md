# 任务

阶段4_1: cwe信息补全.

## TODO:
对于cpp_check, 尝试提取所有 rule_id 并进行去重, 然后挨个分析能与数据中的哪个条目匹配得上, 能正确匹配则采用.


## ALREADY:
`data_remaining.json` 是本阶段需处理的数据.

本阶段任务: 从 `input/cwe_information` 中找到能够与 `data_remaining.json` 中的条目(尤其是 rule_id) 相匹配的信息, 然后为 `data_remaining.json` 补全 CWE 信息(存在许多cwe不完整, 或是根本没有的条目)

这是一个比较复杂的任务, 难点在于:

- `cwe_information` 中的信息比较杂乱, 形式较多, 不统一.
- `data_remaining.json` 的 rule_id 可能只有特定部分能够匹配上. 建议先从中提取所有的 rule_id 去重, 若最终 rule_id 条目不多, 则可以直接分析并进行映射.


# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.


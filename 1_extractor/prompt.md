# 任务

帮我从 input/data 的四个工具中提取源码警告到 data_all.json 中, 每个警告模板在 input/sample.json.

提取完成后帮我进行数据分析, 统计每个工具, 每个版本, 每个cwe(或无cwe) 的数据情况, 同样写为 python 脚本, 分析结果也导出为 md 格式.

# 注意事项

1. project_name_with_version, project_version, project_name 建议与 input/repository 中的对应仓库对齐, 因为后续要从这些仓库提取源代码.
2. 不同警告工具的警告呈现形式不一应, 可能要用不同的方式进行提取.
3. 程序输出全部放在 output/ 目录下.
4. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
# 任务

TODO:
再次变更需求. 现在合并逻辑我已经在外部实现. 现在要做的很简单, 从 data_all_labeled.json 中分离出不存在于 llm_results_with_annotated_data_2510.json 的数据. 


存在性判定:
tool_name, project_name_with_version, file_path, line_number 均一致则意味着条目相同.

# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.
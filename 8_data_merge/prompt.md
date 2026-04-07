# 任务

阶段8: 新旧数据合并

## TODO:
`input/previous`中有之前处理的旧数据,  `llm_results_with_annotated_data_1025.json`是不一致数据的人工标注, `llm_results_with_annotated_data_2510.json` 是合并了一致数据的结果. `input`中还有873和2386两个文件, 是新的数据(已经处理完), 我希望你将先前工作与当前目录的结果进行合并, 分别得出两个文件, 一个是只包含不一致的人工标注结果(旧 + 新), 一个是包含所有条目(旧 + 新, 一致 + 不一致), 并且进行重新id编号, 旧文件id保持不变.
合并完对完成合并的数据进行数据分析, 包括cwe, TP/FP, project, tool等维度.

## ALREADY:

# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.
5. 对于每次程序变更, 应当同时更新必要文档, 避免文档落后于项目.

# 补充
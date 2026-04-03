# 任务

阶段4_2: 警告数据过滤筛选.

## TODO:
本阶段需要对警告数据集进行筛选, 筛选规则如下:
1. 筛选出所有包含 `input/cwe-top25` 中存在的 cwe 的条目.
2. 去除所有 `file_path` 中属于测试文件的条目(测试文件命名可能比较多样, 需要具体问题具体分析).
3. 根据 `project_name_with_version`, `file_path`, `line_number` 可从 `input/repository` 中获取对应行的源代码, 去除所有目标行代码是 `# define` 的这类数据.
4. 每个项目都有多个版本, 对于每个 project, 去除出现的最后一个版本的数据.
5. 筛选完后进行一个简单的数据分析, 统计下筛选结果, 以及 cwe 和 project 和 tool 的分布情况.


## ALREADY:

# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.
5. 对于每次程序变更, 应当同时更新必要文档, 避免文档落后于项目.


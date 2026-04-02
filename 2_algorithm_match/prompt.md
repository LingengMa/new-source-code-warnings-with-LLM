# 任务

该阶段任务是对data_all.json中的数据进行算法匹配并给出匹配标签.
匹配算法已经给出, 设计如docs/DESIGN.md, 程序在match.py和trackeer.py, 但都是旧仓库直接copy, 字段名/文件名等细节需要进行调整.
请帮我进行调整并执行.

# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.
# 数据集处理仓库 (new)

数据集构建顺序:

1. 警告提取(extractor)
2. 算法匹配 (algorithm_match)
3. 过滤, 筛选, 并进行编号 (data_prepare)

   - CWE 拼接

   - 筛选 CWE top25

   - 去除 test 警告

   - 去除 #define 的警告
   - 去除最后版本
4. 已有数据分离 (existing_data_separation)
5. 切片提取 (slice/slice_joern)
6. 大模型匹配 (llm_match)
7. 人工标注 (annotate)



资源位置:

- public/repositories 各个代码仓库源码(软链接)
- annotations_raw 原始的各种警告数据


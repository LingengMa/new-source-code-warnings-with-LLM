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
# 任务

阶段7: 人工标注

## TODO:
目前数据分析已经结束, 我希望你帮我完成:
1. 人工标注的数据是五种标签不完全一致的条目, 接下来需要将标注结果与一致的数据进行合并, 一致数据的标注可以参考下面的条目.

```
{
    "id": 4,
    "tool_name": "codeql",
    "project_name": "ffmpeg",
    "project_name_with_version": "ffmpeg-6.1.1",
    "project_version": "6.1.1",
    "file_path": "libavcodec/x86/snowdsp.c",
    "line_number": 80,
    "cwe": [
      "CWE-120",
      "CWE-125"
    ],
    "rule_id": "cpp/offset-use-before-range-check",
    "message": "This use of offset 'i' should follow the [range check](1).",
    "severity": null,
    "function_name": "<global>",
    "label": "FP",
    "llm_results": {
      "wuwl": {
        "llm_label": "FP",
        "llm_label_reason": "告警所在行的循环条件 `i<w_r` 已对索引 `i` 进行了范围检查，确保 `dst[i]` 的访问不会越界。切片代码中 `w_r` 的计算 (`w2 - 1`) 和循环逻辑表明访问是安全的。",
        "mode_desc": "三分类+含算法标签"
      },
      "wuol": {
        "llm_label": "FP",
        "llm_label_reason": "切片代码显示，在警告所在行 `for(; (((x86_reg)&dst[i]) & 0x1F) && i<w_r; i++){` 中，对索引 `i` 的使用（`dst[i]`）之前已经通过 `i<w_r` 条件进行了范围检查，确保了 `i` 在有效范围内，因此不存在越界访问风险。",
        "mode_desc": "三分类+不含算法标签"
      },
      "ouwl": {
        "llm_label": "FP",
        "llm_label_reason": "告警所在行的循环条件 `i<w_r` 已对索引 `i` 进行了范围检查，确保 `dst[i]` 的访问在有效范围内。切片代码中未发现明显的越界访问风险。",
        "mode_desc": "二分类+含算法标签"
      },
      "ouol": {
        "llm_label": "FP",
        "llm_label_reason": "切片代码中，在警告所在行的循环条件 `i<w_r` 已经对索引 `i` 进行了范围检查，确保了 `dst[i]` 的访问不会越界。该条件与地址对齐检查 `(((x86_reg)&dst[i]) & 0x1F)` 共同构成了有效的防护。",
        "mode_desc": "二分类+不含算法标签"
      }
    },
    "sliced_code": "xxx",
    "manual_annotation": "FP",
    "annotation_reason": "所有标签（算法标签及四种LLM标签）完全一致，无需人工审核，自动采用一致标签。",
    "annotation_timestamp": "2026-04-02T16:35:14.170166+00:00"
  },
```


## ALREADY:
该子仓库的功能是对已有的数据进行人工标注, 目前根据算法匹配得出 `label`, 以及大模型匹配得出四种大模型标注的标签, 需要人工标注的对象是这五种标签不完全一致的条目. 我需要你:
1. 写一个脚本, 分离出需要进行人工标注的子集.
2. 调整src中的内容细节, 适配当前数据.

# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.
5. 对于每次程序变更, 应当同时更新必要文档, 避免文档落后于项目.

# 补充
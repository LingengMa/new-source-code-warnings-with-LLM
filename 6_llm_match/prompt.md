# 任务

阶段6: 大模型匹配

## TODO:

该子仓库的功能是对阶段5的输出 `slices_for_llm_with_label.json` 进行四种大模型匹配, 根据现有字段按需进行匹配, 从而获取大模型匹配结果.

提示词已经构建完毕, 分别是双分类 / 三分类提示词, 以及带 label / 不带 leble 提示词组合出的四种匹配方式.

每一次大模型调用仅进行一条数据的一种匹配, 即每条数据需要匹配四次.

匹配完后合并结果并且进行数据分析.

最终结果示例:

```json
 {
    "id": 1,
    "tool_name": "codeql",
    "project_name": "ffmpeg",
    "project_name_with_version": "ffmpeg-6.1.1",
    "project_version": "6.1.1",
    "file_path": "fftools/ffprobe.c",
    "line_number": 1053,
    "cwe": [
      "CWE-120",
      "CWE-125"
    ],
    "rule_id": "cpp/offset-use-before-range-check",
    "message": "This use of offset 'i' should follow the [range check](1).",
    "severity": null,
    "function_name": "upcase_string",
    "label": "FP",
    "llm_results": {
      "wuwl": {
        "llm_label": "FP",
        "llm_label_reason": "循环条件 `src[i] && i < dst_size-1` 确保了只有当 `i` 小于 `dst_size-1` 且 `src[i]` 不为空字符时才会进入循环体，循环结束后 `i` 的值要么等于 `dst_size-1`，要么指向 `src` 字符串的结尾空字符，因此 `dst[i] = 0;` 的赋值操作是安全的，不会发生越界。",
        "mode_desc": "三分类+含算法标签"
      },
      "wuol": {
        "llm_label": "TP",
        "llm_label_reason": "循环条件 `src[i] && i < dst_size-1` 在检查 `i` 是否小于 `dst_size-1` 之前，先访问了 `src[i]`，这可能导致在 `i` 等于或超过 `dst_size-1` 时，`src[i]` 的访问越界。",
        "mode_desc": "三分类+不含算法标签"
      },
      "ouwl": {
        "llm_label": "FP",
        "llm_label_reason": "循环条件 `src[i] && i < dst_size-1` 确保了在访问 `src[i]` 和 `dst[i]` 之前，索引 `i` 已通过 `i < dst_size-1` 进行了范围检查，因此不存在偏移量在范围检查前使用的问题。",
        "mode_desc": "二分类+含算法标签"
      },
      "ouol": {
        "llm_label": "FP",
        "llm_label_reason": "切片代码显示循环条件 `src[i] && i < dst_size-1` 确保了在访问 `src[i]` 之前，`i` 已通过 `i < dst_size-1` 进行了范围检查，因此不存在偏移量在范围检查前使用的问题。",
        "mode_desc": "二分类+不含算法标签"
      }
    },
    "sliced_code": "// ========== Sliced Code ==========\n\nstatic inline char *upcase_string(char *dst, size_t dst_size, const char *src)\n{\n    for (i = 0; src[i] && i < dst_size-1; i++)  // The line where the warning is located\n        dst[i] = av_toupper(src[i]);\n    dst[i] = 0;\n    return dst;\n}\n\n\n// ========== Called Function Definitions ==========\n\n// Function: av_toupper from libavutil/avstring.h (lines 227-232)\nstatic inline av_const int av_toupper(int c)\n{\n    if (c >= 'a' && c <= 'z')\n        c ^= 0x20;\n    return c;\n}\n\n"
  }
```

目前已给出了初步实现, 需进行简单调整.

## ALREADY:

# 注意事项
1. 程序输出全部放在 output/ 目录下.
2. 补全必要文档, 如 README.md, 除 README 外, 必要文档全写在 docs/ 目录下
3. 虚拟环境使用 conda, 需包含requirements.txt, 环境创建的简单信息可以写在 README 中.
4. 发现 input/ 目录内的数据出现问题, 应当从上一阶段的子项目进行查找, 而非由该子项目进行适配.
5. 对于每次程序变更, 应当同时更新必要文档, 避免文档落后于项目.

# 补充

deepseek接口提供了 JSON Output 功能, 可以优化现有代码, 不必再用提示词限制 json, 直接使用 JSON Output 即可.

这里展示了使用 JSON Output 功能的完整 Python 代码：

```
import json
from openai import OpenAI

client = OpenAI(
    api_key="<your api key>",
    base_url="https://api.deepseek.com",
)

system_prompt = """
The user will provide some exam text. Please parse the "question" and "answer" and output them in JSON format. 

EXAMPLE INPUT: 
Which is the highest mountain in the world? Mount Everest.

EXAMPLE JSON OUTPUT:
{
    "question": "Which is the highest mountain in the world?",
    "answer": "Mount Everest"
}
"""

user_prompt = "Which is the longest river in the world? The Nile River."

messages = [{"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}]

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=messages,
    response_format={
        'type': 'json_object'
    }
)

print(json.loads(response.choices[0].message.content))
```


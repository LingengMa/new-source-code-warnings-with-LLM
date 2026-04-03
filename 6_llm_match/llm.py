"""
大模型匹配脚本 — 对每条警告进行 TP/FP(/Unknown) 分类。

使用 DeepSeek JSON Output 模式，通过 system/user 双消息格式调用，
无需在提示词中限制输出格式，API 直接返回合法 JSON。

用法：
    python llm.py --mode with_unknown_without_label     # 三分类，不含算法标签
    python llm.py --mode without_unknown_without_label  # 二分类，不含算法标签
    python llm.py --mode with_unknown_with_label        # 三分类，含算法标签
    python llm.py --mode without_unknown_with_label     # 二分类，含算法标签
"""

import json
import argparse
from openai import OpenAI
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


# ──────────────────────────────────────────────
# 四种模式配置表
# mode 名称 → (prompt模块, 输入文件, 输出文件)
# ──────────────────────────────────────────────
UNIFIED_INPUT = "input/slices_for_llm_with_label.json"

MODES = {
    "with_unknown_without_label": {
        "prompt_module": "prompts.prompt_with_unknown_without_label",
        "input_file":    UNIFIED_INPUT,
        "output_file":   "output/results_with_unknown_without_label.json",
        "description":   "三分类(TP/FP/Unknown)，不含算法参考标签",
        "strip_label":   True,   # 发送给LLM前剔除 label 字段
    },
    "without_unknown_without_label": {
        "prompt_module": "prompts.prompt_without_unknown_without_label",
        "input_file":    UNIFIED_INPUT,
        "output_file":   "output/results_without_unknown_without_label.json",
        "description":   "二分类(TP/FP)，不含算法参考标签",
        "strip_label":   True,
    },
    "with_unknown_with_label": {
        "prompt_module": "prompts.prompt_with_unknown_with_label",
        "input_file":    UNIFIED_INPUT,
        "output_file":   "output/results_with_unknown_with_label.json",
        "description":   "三分类(TP/FP/Unknown)，含算法参考标签",
        "strip_label":   False,
    },
    "without_unknown_with_label": {
        "prompt_module": "prompts.prompt_without_unknown_with_label",
        "input_file":    UNIFIED_INPUT,
        "output_file":   "output/results_without_unknown_with_label.json",
        "description":   "二分类(TP/FP)，含算法参考标签",
        "strip_label":   False,
    },
}

# 配置API密钥（从环境变量获取）
client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)


def process_data_with_llm(data, system_prompt, strip_label=False, retries=3, retry_delay=5):
    """
    使用LLM处理单条数据，包含重试机制。

    使用 DeepSeek JSON Output 模式：system 消息承载分析指令，user 消息仅传入
    待分析的 JSON 数据。response_format={'type': 'json_object'} 确保返回合法 JSON，
    无需在提示词中额外限制输出格式。

    strip_label=True 时，发送给LLM的数据中剔除 label 字段，但结果中仍保留原始 label。
    """
    data_for_llm = {k: v for k, v in data.items() if not (strip_label and k == "label")}
    user_content = json.dumps(data_for_llm, indent=2, ensure_ascii=False)

    for attempt in range(retries):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_content},
                ],
                response_format={"type": "json_object"},
                stream=False,
                temperature=0.1,
            )

            llm_output = response.choices[0].message.content
            result = json.loads(llm_output)
            # 合并完整原始数据（含 label）到结果中
            result.update(data)
            return result

        except json.JSONDecodeError:
            print(f"警告：ID {data.get('id')} 无法解析LLM返回的JSON，将不会重试。原始输出: {llm_output}")
            return None
        except Exception as e:
            print(f"错误：ID {data.get('id')} 调用API时出错: {e}。正在进行第 {attempt + 1}/{retries} 次重试...")
            if attempt < retries - 1:
                time.sleep(retry_delay)
            else:
                print(f"错误：ID {data.get('id')} 在重试 {retries} 次后仍然失败。")
                return None
    return None


def run(mode: str):
    """
    主运行函数，根据指定模式读取数据、处理并保存结果
    """
    if mode not in MODES:
        print(f"错误：未知模式 '{mode}'，可用模式：{list(MODES.keys())}")
        return

    cfg = MODES[mode]
    print(f"\n{'='*60}")
    print(f"运行模式：{mode}")
    print(f"描述：{cfg['description']}")
    print(f"输入：{cfg['input_file']}")
    print(f"输出：{cfg['output_file']}")
    print(f"{'='*60}\n")

    # 动态加载对应的提示词模板（作为 system 消息内容）
    import importlib
    prompt_mod = importlib.import_module(cfg["prompt_module"])
    system_prompt = prompt_mod.PROMPT_TEMPLATE
    strip_label = cfg["strip_label"]

    input_filepath  = cfg["input_file"]
    output_filepath = cfg["output_file"]

    # 确保输出目录存在
    output_dir = os.path.dirname(output_filepath)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 读取输入数据
    with open(input_filepath, 'r', encoding='utf-8') as f:
        input_data = json.load(f)

    results = []
    processed_ids = set()

    # 断点续传：加载已有结果
    if os.path.exists(output_filepath):
        try:
            with open(output_filepath, 'r', encoding='utf-8') as f:
                results = json.load(f)
                processed_ids = {item['id'] for item in results if 'id' in item}
                print(f"已加载 {len(results)} 条已有结果，将从断点处继续。")
        except (json.JSONDecodeError, IOError) as e:
            print(f"警告：无法加载或解析现有结果文件，将重新开始。错误: {e}")
            results = []
            processed_ids = set()

    # 过滤掉已处理的数据
    tasks_to_process = [item for item in input_data if item.get('id') not in processed_ids]

    if not tasks_to_process:
        print("所有数据均已处理完毕。")
        return

    total_tasks = len(tasks_to_process)
    print(f"共有 {total_tasks} 条新数据待处理。")

    processed_count = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_data = {
            executor.submit(process_data_with_llm, data_item, system_prompt, strip_label): data_item
            for data_item in tasks_to_process
        }

        for future in as_completed(future_to_data):
            data_item = future_to_data[future]
            try:
                result = future.result()
                if result:
                    results.append(result)
                    print(f"处理成功: ID {result['id']}")
                else:
                    print(f"处理失败: ID {data_item.get('id')}")

                processed_count += 1

                # 每处理10条数据保存一次
                if processed_count % 10 == 0:
                    with open(output_filepath, 'w', encoding='utf-8') as f:
                        json.dump(sorted(results, key=lambda x: x.get('id', 0)), f, indent=2, ensure_ascii=False)
                    print(f"--- 进度已保存：已处理 {processed_count}/{total_tasks} ---")

            except Exception as exc:
                print(f"ID {data_item.get('id')} 在处理时产生异常: {exc}")

    # 最终保存所有结果（按 id 排序）
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(sorted(results, key=lambda x: x.get('id', 0)), f, indent=2, ensure_ascii=False)

    print(f"\n处理完成！总共 {len(results)} 条结果已保存到 {output_filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="静态分析告警LLM分类工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n可用模式：\n" + "\n".join(
            f"  {k:<40} {v['description']}" for k, v in MODES.items()
        )
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=list(MODES.keys()),
        required=True,
        help="运行模式，决定使用哪套提示词和输入/输出文件"
    )
    args = parser.parse_args()
    run(args.mode)


if __name__ == "__main__":
    main()
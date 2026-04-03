"""
兜底恢复脚本
对 output/slices.json 中状态为 error 的条目执行兜底逻辑：
  1. 尝试定位源文件（直接路径优先，若不存在则在仓库目录中按文件名搜索）
  2. 提取 line_number 前后各 CONTEXT_SIZE 行作为切片
  3. 将恢复结果回写到 output/slices.json 及所有派生文件
"""
import json
import logging
import os
import sys

import config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CONTEXT_SIZE = config.CONTEXT_SIZE  # 前后各取多少行（默认 50）


def find_file_in_repo(project_dir: str, file_path: str) -> str | None:
    """
    在项目仓库目录中定位源文件。
    先尝试直接拼接路径，若不存在则递归搜索同名文件（basename 匹配）。

    Returns:
        找到的绝对路径，未找到返回 None
    """
    direct = os.path.join(project_dir, file_path)
    if os.path.exists(direct):
        return direct

    basename = os.path.basename(file_path)
    # 递归查找同名文件
    for root, _, files in os.walk(project_dir):
        if basename in files:
            return os.path.join(root, basename)
    return None


def context_extract(code_lines: list[str], target_line: int, context_size: int) -> tuple[str, list[int]]:
    """
    提取 target_line 前后各 context_size 行。

    Args:
        code_lines: 文件所有行（0-based 列表）
        target_line: 目标行号（1-based）
        context_size: 前后各取多少行

    Returns:
        (代码字符串, 行号列表（1-based）)
    """
    total = len(code_lines)
    start = max(1, target_line - context_size)
    end = min(total, target_line + context_size)
    lines = code_lines[start - 1:end]
    code = "".join(lines)
    line_numbers = list(range(start, end + 1))
    return code, line_numbers


def recover_entry(entry: dict) -> dict:
    """
    对单条 error 条目执行兜底恢复。
    返回更新后的 entry（in-place 修改并返回）。
    """
    project_name = entry.get("project_name_with_version", "")
    file_path = entry.get("file_path", "")
    target_line = entry.get("line_number", 0)
    original_error = entry.get("error", "")

    project_dir = os.path.join(config.REPOSITORY_DIR, project_name)
    if not os.path.isdir(project_dir):
        logging.warning(f"Project dir not found: {project_dir}")
        entry["status"] = "error"
        entry["error"] = f"Project directory not found: {project_dir}"
        return entry

    full_path = find_file_in_repo(project_dir, file_path)
    if not full_path:
        logging.warning(f"Cannot locate file {file_path} in {project_dir}")
        entry["status"] = "error"
        entry["error"] = f"File not found in repository: {file_path}"
        return entry

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            code_lines = f.readlines()
    except Exception as e:
        entry["status"] = "error"
        entry["error"] = f"Failed to read {full_path}: {e}"
        return entry

    sliced_code, slice_line_numbers = context_extract(code_lines, target_line, CONTEXT_SIZE)

    resolved_path = os.path.relpath(full_path, os.path.join(config.REPOSITORY_DIR, project_name))

    entry["status"] = "context_fallback"
    entry["sliced_code"] = sliced_code
    entry["complete_code"] = sliced_code
    entry["slice_lines"] = slice_line_numbers
    entry["enhanced_slice_lines"] = slice_line_numbers
    entry["called_functions"] = []
    entry["function_definitions"] = {}
    entry["function_name"] = None
    entry["function_start_line"] = None
    entry["function_end_line"] = None
    entry["metadata"] = {
        "slice_type": "context_extraction",
        "context_size": CONTEXT_SIZE,
        "extraction_reason": "error_fallback",
        "original_error": original_error,
        "resolved_file_path": resolved_path,
    }
    # 清除之前的 error / traceback 字段
    entry.pop("error", None)
    entry.pop("traceback", None)

    logging.info(
        f"Recovered {project_name}/{file_path}:{target_line} "
        f"-> {len(slice_line_numbers)} lines (resolved: {resolved_path})"
    )
    return entry


def rebuild_derived_files(results: list[dict], output_path: str) -> None:
    """重建所有派生输出文件。"""
    # summary
    summary_path = output_path.replace(".json", "_summary.json")
    summary = []
    for r in results:
        item = {
            "id": r.get("id"),
            "project_name_with_version": r.get("project_name_with_version"),
            "file_path": r.get("file_path"),
            "line_number": r.get("line_number"),
            "status": r.get("status"),
            "function_name": r.get("function_name"),
            "slice_lines_count": len(r.get("slice_lines", [])),
            "enhanced_lines_count": len(r.get("enhanced_slice_lines", [])),
            "metadata": r.get("metadata", {}),
        }
        if r.get("status") == "error":
            item["error"] = r.get("error")
        summary.append(item)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logging.info(f"Summary saved: {summary_path}")

    # for_llm (no label)
    llm_path = output_path.replace(".json", "_for_llm.json")
    llm = []
    for r in results:
        llm.append({
            "id": r.get("id"),
            "tool_name": r.get("tool_name"),
            "project_name_with_version": r.get("project_name_with_version"),
            "project_version": r.get("project_version"),
            "line_number": r.get("line_number"),
            "function_name": r.get("function_name"),
            "rule_id": r.get("rule_id"),
            "message": r.get("message"),
            "sliced_code": r.get("complete_code") or r.get("sliced_code"),
        })
    with open(llm_path, "w", encoding="utf-8") as f:
        json.dump(llm, f, indent=2, ensure_ascii=False)
    logging.info(f"LLM format saved: {llm_path}")

    # for_llm_with_label
    llm_label_path = output_path.replace(".json", "_for_llm_with_label.json")
    llm_label = []
    for r in results:
        llm_label.append({
            "id": r.get("id"),
            "tool_name": r.get("tool_name"),
            "project_name_with_version": r.get("project_name_with_version"),
            "project_version": r.get("project_version"),
            "line_number": r.get("line_number"),
            "function_name": r.get("function_name"),
            "rule_id": r.get("rule_id"),
            "message": r.get("message"),
            "sliced_code": r.get("complete_code") or r.get("sliced_code"),
            "label": r.get("label"),
        })
    with open(llm_label_path, "w", encoding="utf-8") as f:
        json.dump(llm_label, f, indent=2, ensure_ascii=False)
    logging.info(f"LLM format with label saved: {llm_label_path}")


def main() -> None:
    output_path = config.OUTPUT_JSON
    if not os.path.exists(output_path):
        logging.error(f"slices.json not found: {output_path}")
        sys.exit(1)

    logging.info(f"Loading {output_path} ...")
    with open(output_path, "r", encoding="utf-8") as f:
        results = json.load(f)

    failed = [r for r in results if r.get("status") == "error"]
    logging.info(f"Total entries: {len(results)}, failed: {len(failed)}")

    if not failed:
        logging.info("No failed entries, nothing to do.")
        return

    recovered = 0
    still_failed = 0
    for entry in results:
        if entry.get("status") != "error":
            continue
        recover_entry(entry)
        if entry.get("status") != "error":
            recovered += 1
        else:
            still_failed += 1

    logging.info(f"Recovered: {recovered}, still failed: {still_failed}")

    # 保存更新后的 slices.json
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logging.info(f"Updated slices.json saved: {output_path}")

    # 重建派生文件
    rebuild_derived_files(results, output_path)

    # 打印最终统计
    status_counts: dict[str, int] = {}
    for r in results:
        s = r.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
    logging.info("Final status distribution:")
    for s, cnt in sorted(status_counts.items()):
        logging.info(f"  {s}: {cnt}")


if __name__ == "__main__":
    main()

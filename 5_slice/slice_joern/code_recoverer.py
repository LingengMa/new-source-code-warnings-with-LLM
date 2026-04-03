"""
代码恢复模块
将带占位符的代码恢复为完整代码
"""
from typing import Dict, Set, List
import logging
import config


def recover_placeholder(code_with_placeholder: str,
                       slice_lines: Set[int],
                       source_lines: Dict[int, str],
                       all_lines: Set[int],
                       placeholder: str = config.PLACEHOLDER) -> str:
    """
    将带占位符的代码恢复为完整代码
    
    Args:
        code_with_placeholder: 带占位符的代码（通常是 LLM 生成的修复代码）
        slice_lines: 原始切片的行号集合
        source_lines: 原始源代码行字典
        all_lines: 函数的所有行号集合
        placeholder: 占位符字符串
    
    Returns:
        完整的代码字符串
    """
    from code_extractor import reduced_hunks
    
    # 生成被省略的代码块
    placeholder_hunks = reduced_hunks(slice_lines, source_lines, all_lines)
    
    if not placeholder_hunks:
        # 没有被省略的代码，直接返回
        return code_with_placeholder
    
    # 计算期望的占位符数量
    expected_placeholders = code_with_placeholder.count(placeholder.strip())
    
    if expected_placeholders != len(placeholder_hunks):
        logging.warning(
            f"Placeholder count mismatch: expected {len(placeholder_hunks)}, "
            f"found {expected_placeholders}"
        )
        # 数量不匹配，无法恢复
        return None
    
    # 逐行替换占位符
    result = ""
    for line in code_with_placeholder.split("\n"):
        if line.strip().lower() == placeholder.strip().lower():
            # 替换占位符为实际代码
            if placeholder_hunks:
                result += placeholder_hunks.pop(0)
        else:
            result += line + "\n"
    
    logging.info(f"Successfully recovered {expected_placeholders} placeholders")
    return result


def recover_batch(results: List[Dict],
                 source_files: Dict[str, Dict[int, str]],
                 placeholder: str = config.PLACEHOLDER) -> List[Dict]:
    """
    批量恢复多个结果的占位符
    
    Args:
        results: 切片结果列表
        source_files: 源文件字典 {文件路径: {行号: 代码行}}
        placeholder: 占位符字符串
    
    Returns:
        恢复后的结果列表
    """
    recovered_results = []
    
    for result in results:
        if result.get('status') != 'success':
            recovered_results.append(result)
            continue
        
        # 获取必要信息
        file_path = result.get('file')
        slice_lines = set(result.get('slice_lines', []))
        function_start = result.get('function_start_line', 1)
        function_end = result.get('function_end_line', 1)
        code_with_ph = result.get('sliced_code_with_placeholder')
        
        if not all([file_path, slice_lines, code_with_ph]):
            recovered_results.append(result)
            continue
        
        # 获取源代码
        if file_path not in source_files:
            logging.warning(f"Source file not found: {file_path}")
            recovered_results.append(result)
            continue
        
        source_lines = source_files[file_path]
        all_lines = set(range(function_start, function_end + 1))
        
        # 恢复占位符
        recovered_code = recover_placeholder(
            code_with_ph,
            slice_lines,
            source_lines,
            all_lines,
            placeholder
        )
        
        # 更新结果
        result_copy = result.copy()
        if recovered_code:
            result_copy['recovered_code'] = recovered_code
            result_copy['recovery_status'] = 'success'
        else:
            result_copy['recovery_status'] = 'failed'
        
        recovered_results.append(result_copy)
    
    # 统计
    success = sum(1 for r in recovered_results if r.get('recovery_status') == 'success')
    logging.info(f"Recovered {success}/{len(results)} results")
    
    return recovered_results

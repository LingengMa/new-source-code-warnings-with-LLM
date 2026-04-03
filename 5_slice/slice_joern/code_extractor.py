"""
代码提取模块
从切片节点集合提取源代码，支持占位符模式
"""
from typing import Dict, Set, Optional, List, Tuple
import logging
import re
import config

try:
    from function_extractor import extract_called_functions
    FUNCTION_EXTRACTION_AVAILABLE = True
except ImportError:
    FUNCTION_EXTRACTION_AVAILABLE = False
    logging.warning("Function extraction not available")

try:
    from treesitter_extractor import extract_called_functions_treesitter, TREE_SITTER_AVAILABLE
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logging.warning("Tree-sitter extraction not available")


def collapse_trailing_braces(code: str) -> str:
    """
    折叠切片末尾真正多余的纯关闭括号行。

    只处理以下情况：整段切片代码（含末尾 `}`）的净括号值 < 0，
    即存在真正多余的 `}`（比对应的 `{` 还多）。此时从末尾截去
    多余的 `}` 行，使净值恢复到 0。

    对于净值 == 0（括号完全平衡）或净值 > 0（缺少闭括号，应由
    balance_braces 补全）的情况，此函数不做任何修改。
    """
    if not code:
        return code

    def _count_net(src: str) -> int:
        """统计净未关闭 { 数（忽略字符串/注释），正数=缺闭括号，负数=多余闭括号"""
        depth = 0
        i = 0
        n = len(src)
        while i < n:
            c = src[i]
            if c == '/' and i + 1 < n and src[i + 1] == '/':
                while i < n and src[i] != '\n':
                    i += 1
                continue
            if c == '/' and i + 1 < n and src[i + 1] == '*':
                i += 2
                while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                    i += 1
                i += 2
                continue
            if c == '"':
                i += 1
                while i < n and src[i] != '"':
                    if src[i] == '\\': i += 1
                    i += 1
                i += 1
                continue
            if c == "'":
                i += 1
                while i < n and src[i] != "'":
                    if src[i] == '\\': i += 1
                    i += 1
                i += 1
                continue
            if c == '{': depth += 1
            elif c == '}': depth -= 1
            i += 1
        return depth

    net = _count_net(code)

    # 净值 >= 0：括号平衡或缺少闭括号，不处理（留给 balance_braces）
    if net >= 0:
        return code

    # 净值 < 0：有 |net| 个真正多余的 `}`，从末尾删除
    excess = -net  # 需要删除的 } 行数

    _CLOSE_ONLY_RE = re.compile(r'^\s*\}\s*$')
    _BLANK_RE = re.compile(r'^\s*$')
    lines = code.splitlines(keepends=True)

    # 从末尾跳过空行，再向前逐个删除纯 } 行
    i = len(lines) - 1
    while i >= 0 and _BLANK_RE.match(lines[i]):
        i -= 1
    tail_end = i + 1  # 空行区域起始（exclusive end of non-blank）

    removed = 0
    remove_indices = set()
    while i >= 0 and removed < excess:
        if _CLOSE_ONLY_RE.match(lines[i]):
            remove_indices.add(i)
            removed += 1
        i -= 1

    if not remove_indices:
        return code

    result_lines = [ln for idx, ln in enumerate(lines) if idx not in remove_indices]
    result = "".join(result_lines)
    logging.debug(
        f"collapse_trailing_braces: removed {removed} excess '}}' lines (net was {net})"
    )
    return result

    logging.debug(
        f"collapse_trailing_braces: reduced {tail_len} trailing '}}' lines to {net_open}"
    )
    return result


def compact_empty_blocks(code: str) -> str:
    """
    折叠切片代码中"体为空"的控制流块（迭代版本）。

    当某行以 `{` 结尾，而下一个非空行是单独的 `}` 时，
    将其折叠为 `{ /* ... */ }`，删除对应的 `}` 行。
    迭代执行直到不再有变化。
    """
    if not code:
        return code

    _CLOSE_ONLY_RE = re.compile(r'^\s*\}\s*$')
    _OPEN_END_RE   = re.compile(r'^(.*\S)\s*\{\s*$')
    _BLANK_RE      = re.compile(r'^\s*$')

    for _ in range(50):
        lines = code.splitlines(keepends=False)
        n = len(lines)
        changed = False

        i = 0
        new_lines = []
        while i < n:
            line = lines[i]
            m = _OPEN_END_RE.match(line)
            if m:
                j = i + 1
                while j < n and _BLANK_RE.match(lines[j]):
                    j += 1
                if j < n and _CLOSE_ONLY_RE.match(lines[j]):
                    new_line = m.group(1) + ' { /* ... */ }'
                    new_lines.append(new_line)
                    i = j + 1
                    changed = True
                    continue
            new_lines.append(line)
            i += 1

        code = '\n'.join(new_lines)
        if code and not code.endswith('\n'):
            code += '\n'
        if not changed:
            break

    return code


def compact_trailing_braces(code: str, max_trailing: int = 3) -> str:
    """
    当切片末尾出现超过 max_trailing 个连续的纯 `}` 行时，
    将多余部分折叠成一行注释，避免末尾堆积大量孤立闭括号。

    策略：
      - 统计末尾连续纯 `}` 行数量 T
      - 若 T <= max_trailing，不处理（少量闭括号是正常的）
      - 若 T > max_trailing，保留最后 max_trailing 个 `}`，
        在它们前面插入一行注释说明有多少个括号被折叠

    注意：此函数不修改括号的实际平衡——被注释掉的 `}` 行在语义上
    仍然代表代码块的结束，注释只是视觉上的折叠，让 LLM 更容易阅读。
    因为括号会变得不平衡（close 减少），调用此函数后不应再调用
    balance_braces 补充 `}`。
    """
    if not code:
        return code

    _CLOSE_ONLY_RE = re.compile(r'^\s*\}\s*$')
    _BLANK_RE = re.compile(r'^\s*$')

    lines = code.splitlines(keepends=False)
    n = len(lines)

    # 从末尾跳过空行
    i = n - 1
    while i >= 0 and _BLANK_RE.match(lines[i]):
        i -= 1

    # 从 i 往前数连续 } 行
    tail_end = i + 1
    trailing_count = 0
    while i >= 0 and _CLOSE_ONLY_RE.match(lines[i]):
        trailing_count += 1
        i -= 1

    if trailing_count <= max_trailing:
        return code  # 不需要处理

    # 折叠多余的 }：保留最后 max_trailing 个，其余替换为注释
    excess = trailing_count - max_trailing
    fold_start = tail_end - trailing_count  # 第一个 } 行的索引
    keep_start = fold_start + excess        # 保留的 } 行起始索引

    # 用第一个 } 行的缩进构造注释行
    first_brace_line = lines[fold_start]
    indent = re.match(r'^(\s*)', first_brace_line).group(1)
    comment_line = f"{indent}/* ... ({excess} closing braces omitted) */"

    new_lines = (
        lines[:fold_start] +
        [comment_line] +
        lines[keep_start:]
    )

    result = '\n'.join(new_lines)
    if result and not result.endswith('\n'):
        result += '\n'

    logging.debug(
        f"compact_trailing_braces: folded {excess} trailing '}}' lines into comment"
    )
    return result


def balance_braces(code: str, language: str = "c") -> str:
    """
    对切片代码进行括号平衡后处理。

    优先使用 tree-sitter AST 解析，通过行集合方式精确补全语法块括号，
    避免基于字符串计数时因缩进层次混乱导致补全位置/顺序错误。
    仅当 tree-sitter 不可用时才退回字符串计数 fallback。

    Args:
        code: 切片代码字符串
        language: 编程语言（默认 "c"）

    Returns:
        括号平衡后的代码字符串
    """
    if not code:
        return code

    # ----------------------------------------------------------------
    # 优先路径：AST 感知的括号补全
    # 将代码按行分解，解析 AST，收集所有行号，用 ASTEnhancer 补全，
    # 再按行号重新拼回。
    # 注意：对于不完整的代码片段（切片拼接后缺少闭括号）tree-sitter 可能
    # 解析为 translation_unit 而找不到 function_definition，此时会抛出
    # 警告并让逻辑自然 fallback 到字符串计数方式。
    # ----------------------------------------------------------------
    try:
        from ast_enhancer import ASTEnhancer, TREE_SITTER_AVAILABLE as _TS_AVAIL
        if _TS_AVAIL:
            enhancer = ASTEnhancer(language)
            lines = code.splitlines(keepends=True)
            all_line_nums: Set[int] = set(range(1, len(lines) + 1))
            line_map: Dict[int, str] = {idx: ln for idx, ln in enumerate(lines, start=1)}

            # 用增强器补全行集合（function_start_line=1，因为 code 是独立片段）
            enhanced_nums = enhancer.enhance_slice(
                source_code=code,
                slice_lines=set(all_line_nums),
                function_start_line=1,
                target_line=None,
            )

            # 若增强后新增了行（即补全了括号行），把这些行从原始代码中取出拼接
            added = enhanced_nums - all_line_nums
            if added:
                logging.debug(
                    f"balance_braces (AST): added {len(added)} lines for brace completion"
                )
                result_lines: Dict[int, str] = dict(line_map)
                for ln_num in added:
                    result_lines[ln_num] = line_map.get(ln_num, "")
                return "".join(result_lines[i] for i in sorted(result_lines))
            # 没有新增行：要么代码已平衡，要么 AST 没识别出函数（不完整代码）
            # 此时不能直接返回，需要继续用字符串计数 fallback 检查是否需要补全
            # —— 因此此处 fall through 到下方 fallback 逻辑
    except Exception as e:
        logging.debug(f"balance_braces: AST path failed ({e}), falling back to string counting")

    # ----------------------------------------------------------------
    # Fallback：字符串计数方式（保留原有逻辑）
    # ----------------------------------------------------------------

    # --- 统计净未闭合 `{` 数（忽略字符串和注释）---
    def _count_unmatched_open(src: str) -> int:
        depth = 0
        i = 0
        n = len(src)
        while i < n:
            c = src[i]
            # 行注释 //
            if c == '/' and i + 1 < n and src[i + 1] == '/':
                while i < n and src[i] != '\n':
                    i += 1
                continue
            # 块注释 /* */
            if c == '/' and i + 1 < n and src[i + 1] == '*':
                i += 2
                while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                    i += 1
                i += 2
                continue
            # 字符串字面量
            if c == '"':
                i += 1
                while i < n and src[i] != '"':
                    if src[i] == '\\':
                        i += 1  # 跳过转义字符
                    i += 1
                i += 1
                continue
            # 字符字面量
            if c == "'":
                i += 1
                while i < n and src[i] != "'":
                    if src[i] == '\\':
                        i += 1
                    i += 1
                i += 1
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            i += 1
        return depth  # 正数表示有 depth 个未闭合的 `{`

    unmatched = _count_unmatched_open(code)
    if unmatched <= 0:
        return code

    logging.debug(f"balance_braces (fallback): found {unmatched} unmatched '{{', appending closing braces")

    # 在代码末尾追加缺失的 `}`，使用最后一个 `}` 行的缩进作为参考
    last_brace_pos = code.rfind('}')
    if last_brace_pos == -1:
        # 没有任何 `}`，直接在末尾追加
        closing = '\n'.join(['}'] * unmatched)
        return code.rstrip('\n') + '\n' + closing + '\n'

    # 以最后一个 `}` 所在行的缩进为参考（通常是 0 缩进或最外层缩进）
    line_start = code.rfind('\n', 0, last_brace_pos) + 1
    last_brace_line = code[line_start:last_brace_pos + 1]
    indent = re.match(r'^(\s*)', last_brace_line).group(1)

    closing_str = ''
    for _ in range(unmatched):
        closing_str += indent + '}\n'

    # 追加到末尾，而非插入到最后一个 `}` 之前（插入会导致 }}}} 连续堆叠）
    return code.rstrip('\n') + '\n' + closing_str


def extract_code(slice_lines: Set[int], 
                source_lines: Dict[int, str], 
                placeholder: Optional[str] = None) -> str:
    """
    从切片行号集合生成源代码
    
    Args:
        slice_lines: 切片包含的行号集合
        source_lines: 原始源代码行字典 {行号: 代码行}
        placeholder: 占位符字符串（可选）
    
    Returns:
        切片代码字符串
    """
    if not slice_lines:
        return ""
    
    # 按行号排序
    sorted_lines = sorted(slice_lines)
    
    # 无占位符模式：直接拼接
    if not placeholder:
        code_parts = []
        for line in sorted_lines:
            if line in source_lines:
                code_parts.append(source_lines[line].rstrip('\n'))
        code = "\n".join(code_parts) + "\n" if code_parts else ""
        code = compact_empty_blocks(code)
        code = collapse_trailing_braces(code)
        opens_before = code.count('{')
        closes_before = code.count('}')
        code = compact_trailing_braces(code)
        opens_after = code.count('{')
        closes_after = code.count('}')
        # 若 compact_trailing_braces 确实折叠了若干 }（close 减少了），
        # 则那些 } 已以注释形式保留，无需再由 balance_braces 补全。
        # 若没有折叠（末尾 } 数量 <= max_trailing），再走 balance_braces 补全缺失的 {。
        folded = closes_before - closes_after
        if folded == 0:
            code = balance_braces(code)
        return code
    
    # 占位符模式：间隔处插入占位符
    code = ""
    last_line = 0
    placeholder_count = 0
    
    for line in sorted_lines:
        if line not in source_lines:
            continue
        
        # 检查是否需要插入占位符
        if line - last_line > 1:
            # 检查间隔是否值得插入占位符
            if _should_insert_placeholder(source_lines, last_line + 1, line - 1):
                code += placeholder + "\n"
                placeholder_count += 1
        
        code += source_lines[line].rstrip('\n') + "\n"
        last_line = line
    
    logging.debug(f"Extracted code with {placeholder_count} placeholders")
    # 占位符模式不做括号平衡（占位符代表省略的代码块，括号已在其中）
    return code


def extract_code_with_warning_marker(slice_lines: Set[int], 
                                     source_lines: Dict[int, str], 
                                     warning_line: int,
                                     placeholder: Optional[str] = None) -> str:
    """
    从切片行号集合生成源代码，并在警告行添加注释标记
    
    Args:
        slice_lines: 切片包含的行号集合
        source_lines: 原始源代码行字典 {行号: 代码行}
        warning_line: 警告所在行号
        placeholder: 占位符字符串（可选）
    
    Returns:
        切片代码字符串，警告行带有注释标记
    """
    if not slice_lines:
        return ""
    
    # 按行号排序
    sorted_lines = sorted(slice_lines)
    
    # 无占位符模式：直接拼接
    if not placeholder:
        code_parts = []
        for line in sorted_lines:
            if line in source_lines:
                code_line = source_lines[line].rstrip('\n')
                # 在警告行添加注释
                if line == warning_line:
                    code_line += "  // The line where the warning is located"
                code_parts.append(code_line)
        code = "\n".join(code_parts) + "\n" if code_parts else ""
        code = compact_empty_blocks(code)
        code = collapse_trailing_braces(code)
        closes_before = code.count('}')
        code = compact_trailing_braces(code)
        closes_after = code.count('}')
        folded = closes_before - closes_after
        if folded == 0:
            code = balance_braces(code)
        return code
    
    # 占位符模式：间隔处插入占位符
    code = ""
    last_line = 0
    placeholder_count = 0
    
    for line in sorted_lines:
        if line not in source_lines:
            continue
        
        # 检查是否需要插入占位符
        if line - last_line > 1:
            # 检查间隙是否值得插入占位符
            if _should_insert_placeholder(source_lines, last_line + 1, line - 1):
                code += placeholder + "\n"
                placeholder_count += 1
        
        code_line = source_lines[line].rstrip('\n')
        # 在警告行添加注释
        if line == warning_line:
            code_line += "  // The line where the warning is located"
        code += code_line + "\n"
        last_line = line
    
    logging.debug(f"Extracted code with {placeholder_count} placeholders and warning marker at line {warning_line}")
    # 占位符模式不做括号平衡（占位符代表省略的代码块，括号已在其中）
    return code


def _should_insert_placeholder(source_lines: Dict[int, str], 
                              start_line: int, 
                              end_line: int) -> bool:
    """
    判断是否应该在代码间隙插入占位符
    
    Args:
        source_lines: 源代码行字典
        start_line: 间隙起始行
        end_line: 间隙结束行
    
    Returns:
        True 如果应该插入占位符
    """
    # 如果间隙只有一行
    if end_line - start_line == 0:
        line = start_line
        if line not in source_lines:
            return False
        
        line_content = source_lines[line].strip()
        
        # 空行或只有注释 - 不插入占位符
        if not line_content or line_content.startswith('//'):
            return False
    
    # 检查间隙中是否全是空行或注释
    has_code = False
    for line in range(start_line, end_line + 1):
        if line not in source_lines:
            continue
        
        content = source_lines[line].strip()
        if content and not content.startswith('//') and not content.startswith('/*'):
            has_code = True
            break
    
    return has_code


def reduced_hunks(slice_lines: Set[int], 
                 source_lines: Dict[int, str],
                 all_lines: Set[int]) -> List[str]:
    """
    生成被省略的代码块列表
    用于占位符恢复
    
    Args:
        slice_lines: 切片包含的行号
        source_lines: 源代码行字典
        all_lines: 方法的所有行号
    
    Returns:
        被省略的代码块列表
    """
    placeholder_lines = all_lines - slice_lines
    hunks = []
    
    # 将连续的行分组
    groups = _group_consecutive_lines(sorted(placeholder_lines))
    
    for group in groups:
        hunk = ""
        for line in group:
            if line in source_lines:
                hunk += source_lines[line].rstrip('\n') + "\n"
        if hunk:
            hunks.append(hunk)
    
    return hunks


def _group_consecutive_lines(lines: List[int]) -> List[List[int]]:
    """
    将连续的行号分组
    
    Args:
        lines: 已排序的行号列表
    
    Returns:
        分组后的列表，每组是连续的行号
    """
    if not lines:
        return []
    
    groups = []
    current_group = [lines[0]]
    
    for i in range(1, len(lines)):
        if lines[i] == lines[i-1] + 1:
            # 连续
            current_group.append(lines[i])
        else:
            # 不连续，开始新组
            groups.append(current_group)
            current_group = [lines[i]]
    
    # 添加最后一组
    groups.append(current_group)
    
    return groups


def extract_code_with_mapping(slice_lines: Set[int],
                              source_lines: Dict[int, str],
                              placeholder: Optional[str] = None) -> tuple[str, Dict[str, str]]:
    """
    提取代码并返回占位符映射
    
    Args:
        slice_lines: 切片行号集合
        source_lines: 源代码行字典
        placeholder: 占位符前缀
    
    Returns:
        (切片代码, 占位符映射字典)
    """
    if not placeholder:
        code = extract_code(slice_lines, source_lines, None)
        return code, {}
    
    placeholder_map = {}
    code = ""
    last_line = 0
    placeholder_counter = 0
    sorted_lines = sorted(slice_lines)
    
    for line in sorted_lines:
        if line not in source_lines:
            continue
        
        # 检查间隙
        if line - last_line > 1:
            if _should_insert_placeholder(source_lines, last_line + 1, line - 1):
                ph_key = f"/* Placeholder_{placeholder_counter} */"
                code += ph_key + "\n"
                
                # 记录被省略的代码
                omitted = ""
                for omit_line in range(last_line + 1, line):
                    if omit_line in source_lines:
                        omitted += source_lines[omit_line]
                
                placeholder_map[ph_key] = omitted
                placeholder_counter += 1
        
        code += source_lines[line].rstrip('\n') + "\n"
        last_line = line
    
    return code, placeholder_map


def extract_code_with_functions(
    slice_lines: Set[int],
    source_lines: Dict[int, str],
    warning_line: int,
    function_start_line: Optional[int] = None,
    function_end_line: Optional[int] = None,
    placeholder: Optional[str] = None,
    extract_functions: bool = True,
    project_root: str = None,
    current_file_path: str = None
) -> Dict:
    """
    增强的代码提取：提取切片代码并包含所有被调用函数的完整定义
    
    Args:
        slice_lines: 切片包含的行号集合
        source_lines: 原始源代码行字典 {行号: 代码行}
        warning_line: 警告所在行号
        function_start_line: 当前函数起始行
        function_end_line: 当前函数结束行
        placeholder: 占位符字符串（可选）
        extract_functions: 是否提取被调用函数的定义
        project_root: 项目根目录（用于跨文件搜索）
        current_file_path: 当前文件的相对路径
    
    Returns:
        {
            "sliced_code": str,                   # 切片代码
            "sliced_code_with_placeholder": str,  # 带占位符的切片代码
            "called_functions": set,              # 调用的函数名集合
            "function_definitions": dict,         # 函数定义字典
            "complete_code": str,                 # 切片代码 + 函数定义
            "complete_code_with_placeholder": str # 带占位符的完整代码
        }
    """
    # 基础提取
    sliced_code = extract_code_with_warning_marker(
        slice_lines=slice_lines,
        source_lines=source_lines,
        warning_line=warning_line,
        placeholder=None
    )
    
    sliced_code_with_placeholder = extract_code_with_warning_marker(
        slice_lines=slice_lines,
        source_lines=source_lines,
        warning_line=warning_line,
        placeholder=placeholder
    )
    
    result = {
        "sliced_code": sliced_code,
        "sliced_code_with_placeholder": sliced_code_with_placeholder,
        "called_functions": set(),
        "function_definitions": {},
        "complete_code": sliced_code,
        "complete_code_with_placeholder": sliced_code_with_placeholder
    }
    
    # 如果不提取函数或不可用，直接返回
    if not extract_functions:
        return result
    
    if not TREE_SITTER_AVAILABLE and not FUNCTION_EXTRACTION_AVAILABLE:
        logging.warning("No function extraction method available")
        return result
    
    # 提取被调用函数 - 优先使用 tree-sitter
    try:
        if TREE_SITTER_AVAILABLE:
            # 使用 tree-sitter 提取（更准确）
            logging.info("Using tree-sitter for function extraction")
            
            # 构建当前文件的完整代码
            current_file_code = "".join(source_lines[i] for i in sorted(source_lines.keys()))
            
            function_definitions, function_calls = extract_called_functions_treesitter(
                sliced_code=sliced_code,
                project_root=project_root,
                current_file_path=current_file_path,
                current_file_code=current_file_code
            )
        else:
            # 回退到正则表达式方法
            logging.info("Using regex-based function extraction")
            function_definitions, function_calls = extract_called_functions(
                sliced_code=sliced_code,
                source_lines=source_lines,
                slice_lines=slice_lines,
                function_start_line=function_start_line,
                function_end_line=function_end_line,
                project_root=project_root,
                current_file_path=current_file_path
            )
        
        result["called_functions"] = function_calls
        result["function_definitions"] = function_definitions
        
        # 构建完整代码（切片 + 函数定义）
        if function_definitions:
            # 生成函数定义部分
            func_defs_code = "\n// ========== Called Function Definitions ==========\n\n"
            for func_name, func_info in sorted(function_definitions.items()):
                file_info = func_info.get('file_path', 'unknown')
                if file_info == 'current':
                    file_info = 'current file'
                
                if func_info.get('is_macro', False):
                    func_defs_code += f"// Macro: {func_name} from {file_info} (line {func_info['start_line']})\n"
                else:
                    func_defs_code += f"// Function: {func_name} from {file_info} (lines {func_info['start_line']}-{func_info['end_line']})\n"
                
                func_defs_code += func_info['code']
                if not func_info['code'].endswith('\n'):
                    func_defs_code += '\n'
                func_defs_code += "\n"
            
            # 组合：切片代码 + 分隔符 + 函数定义
            result["complete_code"] = (
                "// ========== Sliced Code ==========\n\n" +
                sliced_code +
                "\n" +
                func_defs_code
            )
            
            result["complete_code_with_placeholder"] = (
                "// ========== Sliced Code ==========\n\n" +
                sliced_code_with_placeholder +
                "\n" +
                func_defs_code
            )
        
        logging.info(f"Extracted {len(function_definitions)} function definitions for {len(function_calls)} calls")
        
    except Exception as e:
        logging.warning(f"Failed to extract function definitions: {e}")
    
    return result

# ---------------------------------------------------------------------------
# AST 变量追踪切片（PDG 切片失败时的高质量回退方案）
# ---------------------------------------------------------------------------

def ast_variable_slice(
    source_lines: Dict[int, str],
    target_line: int,
    function_start_line: int,
    function_end_line: int,
    language: str = "c",
    max_iterations: int = 3,
) -> Set[int]:
    """
    当 PDG 切片失败时（如 Joern 无法识别函数），使用 tree-sitter 对源文件做
    基于变量使用的语义切片，作为比简单上下文截取更好的回退方案。

    算法：
    1. 用 tree-sitter 解析代码，自动定位目标行所在的真实函数（支持 <global> 场景）
    2. 在该函数范围内提取警告行上出现的所有标识符（变量名）作为种子
    3. 迭代扩展：找出函数范围内所有「定义或使用了这些变量」的语句行
    4. 重复若干轮（传播依赖），直到集合稳定
    5. 用 ASTEnhancer 对每个切片涉及的函数分别补全语法块括号

    Args:
        source_lines: 原始源代码行字典 {行号: 代码行}
        target_line: 警告所在行号（绝对行号）
        function_start_line: PDG 给出的函数起始行号（<global> 时可能是 1）
        function_end_line: PDG 给出的函数结束行号（<global> 时可能是文件末尾）
        language: 编程语言
        max_iterations: 变量追踪的最大迭代轮数

    Returns:
        切片行号集合（绝对行号）；若 tree-sitter 不可用则返回空集合
    """
    try:
        from tree_sitter import Parser
        from tree_sitter_languages import get_language as ts_get_language
    except ImportError:
        logging.warning("tree-sitter not available, ast_variable_slice skipped")
        return set()

    # ---- 准备代码：先取 PDG 给出的范围 ----
    all_source_lines = {
        ln: source_lines[ln]
        for ln in range(function_start_line, function_end_line + 1)
        if ln in source_lines
    }
    if not all_source_lines:
        return set()

    full_code = "".join(all_source_lines[ln] for ln in sorted(all_source_lines))
    file_start = function_start_line  # 该代码块在原始文件中的起始绝对行号

    # ---- 解析 AST ----
    try:
        lang_obj = ts_get_language(language)
        parser = Parser()
        parser.set_language(lang_obj)
        tree = parser.parse(bytes(full_code, "utf8"))
    except Exception as e:
        logging.warning(f"ast_variable_slice: tree-sitter parse failed: {e}")
        return set()

    root = tree.root_node
    target_rel = target_line - file_start + 1  # 相对于 full_code 的行号（1-based）

    # ---- 尝试将切片范围缩小到目标行所在的真实函数 ----
    # 当 PDG 是 <global> 时，function_start/end 覆盖整个文件；
    # 用 tree-sitter 找到目标行所在的 function_definition，缩小范围可以：
    # 1. 减少无关变量污染  2. 让 AST 增强器精确处理该函数的括号
    real_func_start_rel: Optional[int] = None
    real_func_end_rel:   Optional[int] = None

    def _find_func_containing(node, rel_line: int):
        """找到包含 rel_line 的最内层 function_definition"""
        if node.type == "function_definition":
            s = node.start_point[0] + 1
            e = node.end_point[0] + 1
            if s <= rel_line <= e:
                # 继续向子节点递归，找最内层
                for child in node.children:
                    inner = _find_func_containing(child, rel_line)
                    if inner is not None:
                        return inner
                return node
        else:
            for child in node.children:
                result = _find_func_containing(child, rel_line)
                if result is not None:
                    return result
        return None

    real_func_node = _find_func_containing(root, target_rel)
    if real_func_node is not None:
        real_func_start_rel = real_func_node.start_point[0] + 1
        real_func_end_rel   = real_func_node.end_point[0] + 1
        real_func_start_abs = real_func_start_rel + file_start - 1
        real_func_end_abs   = real_func_end_rel   + file_start - 1
        logging.info(
            f"ast_variable_slice: found real function at abs lines "
            f"{real_func_start_abs}-{real_func_end_abs} (target={target_line})"
        )
    else:
        # 找不到函数边界，退回到整个给定范围
        real_func_start_rel = 1
        real_func_end_rel   = len(all_source_lines)
        real_func_start_abs = function_start_line
        real_func_end_abs   = function_end_line
        logging.warning(
            f"ast_variable_slice: no function_definition found containing line {target_line}, "
            f"using full range {function_start_line}-{function_end_line}"
        )

    # ---- C 关键字过滤表 ----
    C_KEYWORDS = {
        "if", "else", "while", "for", "do", "switch", "case", "default",
        "break", "continue", "return", "goto", "sizeof", "typedef", "struct",
        "union", "enum", "const", "static", "extern", "volatile", "inline",
        "void", "int", "char", "short", "long", "float", "double", "unsigned",
        "signed", "auto", "register", "NULL", "true", "false",
    }

    src_bytes = bytes(full_code, "utf8")

    # ---- 构建「相对行 -> 标识符集」映射（仅限真实函数范围内） ----
    line_to_ids: Dict[int, Set[str]] = {
        rel_ln: set()
        for rel_ln in range(real_func_start_rel, real_func_end_rel + 1)
    }

    def _collect_ids(node):
        if node.type == "identifier":
            rel_ln = node.start_point[0] + 1
            name = src_bytes[node.start_byte:node.end_byte].decode("utf8")
            if name not in C_KEYWORDS and rel_ln in line_to_ids:
                line_to_ids[rel_ln].add(name)
        for child in node.children:
            _collect_ids(child)

    _collect_ids(root)

    # ---- 从目标行提取种子变量 ----
    seed_vars: Set[str] = line_to_ids.get(target_rel, set()) - C_KEYWORDS
    logging.info(f"ast_variable_slice: seed variables from line {target_line}: {seed_vars}")

    if not seed_vars:
        # 目标行没有标识符（如纯汇编行），用目标行 ±1 行补充
        for nearby in [target_rel - 1, target_rel + 1, target_rel - 2, target_rel + 2]:
            seed_vars |= line_to_ids.get(nearby, set())
        seed_vars -= C_KEYWORDS
        if not seed_vars:
            logging.warning("ast_variable_slice: no seed variables found, falling back to full function")
            # 返回真实函数全部行
            return set(range(real_func_start_abs, real_func_end_abs + 1))

    # ---- 迭代变量追踪（在真实函数范围内） ----
    tracked_vars: Set[str] = set(seed_vars)
    slice_rel_lines: Set[int] = {target_rel}

    for _iter in range(max_iterations):
        prev_size = len(slice_rel_lines)
        newly_added: Set[int] = set()

        for rel_ln, ids in line_to_ids.items():
            if rel_ln in slice_rel_lines:
                tracked_vars |= ids
                continue
            if ids & tracked_vars:
                newly_added.add(rel_ln)

        slice_rel_lines |= newly_added
        for rel_ln in newly_added:
            tracked_vars |= line_to_ids.get(rel_ln, set())

        logging.info(
            f"ast_variable_slice iter {_iter+1}: "
            f"slice lines {len(slice_rel_lines)}, tracked vars {len(tracked_vars)}"
        )
        if len(slice_rel_lines) == prev_size:
            break

    # ---- 转换为绝对行号 ----
    abs_slice_lines = {rel_ln + file_start - 1 for rel_ln in slice_rel_lines}

    # ---- 用 ASTEnhancer 对所有涉及函数补全语法括号 ----
    # 直接传入整个 full_code（含多函数），enhance_slice 现在会遍历所有函数分别处理
    try:
        from ast_enhancer import enhance_slice_with_ast, TREE_SITTER_AVAILABLE
        if TREE_SITTER_AVAILABLE:
            abs_slice_lines = enhance_slice_with_ast(
                source_code=full_code,
                slice_lines=abs_slice_lines,
                language=language,
                function_start_line=file_start,
                target_line=target_line,
            )
    except Exception as e:
        logging.warning(f"ast_variable_slice: AST enhancement failed: {e}")

    logging.info(
        f"ast_variable_slice: final slice {len(abs_slice_lines)} lines "
        f"(real func {real_func_start_abs}-{real_func_end_abs}, target {target_line})"
    )
    return abs_slice_lines

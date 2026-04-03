"""
函数调用提取器
从切片代码中识别函数调用，并提取这些函数的完整定义
支持在当前文件和整个项目中搜索函数定义
"""
import re
import os
import subprocess
import logging
from typing import Dict, List, Set, Tuple, Optional
from pdg_loader import PDG, PDGNode


class FunctionCallExtractor:
    """函数调用提取器"""
    
    def __init__(self):
        # C/C++ 函数调用的正则表达式
        # 匹配: function_name(args)
        self.function_call_pattern = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')
        
        # C/C++ 关键字和内置函数（不需要提取定义）
        self.c_keywords = {
            'if', 'else', 'while', 'for', 'do', 'switch', 'case', 'default',
            'break', 'continue', 'return', 'goto', 'sizeof', 'typeof',
            'static_cast', 'dynamic_cast', 'reinterpret_cast', 'const_cast',
            '__attribute__', '__builtin_expect', 'offsetof'
        }
        
        # 标准库函数（通常不需要提取）
        self.stdlib_functions = {
            'printf', 'fprintf', 'sprintf', 'snprintf', 'scanf', 'fscanf', 'sscanf',
            'malloc', 'calloc', 'realloc', 'free',
            'strlen', 'strcpy', 'strncpy', 'strcmp', 'strncmp', 'strcat', 'strncat',
            'memcpy', 'memmove', 'memset', 'memcmp',
            'fopen', 'fclose', 'fread', 'fwrite', 'fgets', 'fputs', 'fgetc', 'fputc',
            'exit', 'abort', 'atexit', 'getenv', 'system',
            'assert', 'sizeof'
        }
    
    def extract_function_calls(self, code: str) -> Set[str]:
        """
        从代码中提取所有函数调用
        
        Args:
            code: 源代码字符串
            
        Returns:
            函数名集合
        """
        function_calls = set()
        
        # 移除注释
        code = self._remove_comments(code)
        
        # 提取所有函数调用
        matches = self.function_call_pattern.findall(code)
        
        for func_name in matches:
            # 过滤关键字和标准库函数
            if func_name not in self.c_keywords and func_name not in self.stdlib_functions:
                function_calls.add(func_name)
        
        return function_calls
    
    def _remove_comments(self, code: str) -> str:
        """移除代码中的注释"""
        # 移除单行注释
        code = re.sub(r'//.*?$', '', code, flags=re.MULTILINE)
        # 移除多行注释
        code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
        return code
    
    def extract_function_definitions_from_file(
        self, 
        source_lines: Dict[int, str], 
        function_names: Set[str],
        current_function_lines: Set[int] = None,
        project_root: str = None,
        current_file_path: str = None
    ) -> Dict[str, Dict]:
        """
        从源文件中提取函数定义，支持在项目中搜索
        
        Args:
            source_lines: 行号 -> 代码行的字典（当前文件）
            function_names: 需要提取的函数名集合
            current_function_lines: 当前函数的行号集合（避免重复提取）
            project_root: 项目根目录（用于跨文件搜索）
            current_file_path: 当前文件路径
            
        Returns:
            函数名 -> {start_line, end_line, code, lines, file_path} 的字典
        """
        if current_function_lines is None:
            current_function_lines = set()
        
        function_definitions = {}
        
        # 构建完整代码
        full_code = "".join(source_lines[i] for i in sorted(source_lines.keys()))
        
        for func_name in function_names:
            # 首先在当前文件中查找
            definition = self._find_function_definition(
                full_code, 
                source_lines, 
                func_name,
                current_function_lines
            )
            
            if definition:
                definition['file_path'] = 'current'
                function_definitions[func_name] = definition
            elif project_root and current_file_path:
                # 在项目中搜索
                definition = self._search_function_in_project(
                    func_name,
                    project_root,
                    current_file_path
                )
                if definition:
                    function_definitions[func_name] = definition
        
        return function_definitions
    
    def _search_function_in_project(
        self,
        func_name: str,
        project_root: str,
        current_file_path: str,
        max_files: int = 400
    ) -> Optional[Dict]:
        """
        在项目中搜索函数定义/声明。
        先用 grep 快速定位包含 func_name 的候选文件，再逐一用正则精确解析。
        头文件优先，当前目录优先。
        """
        if not os.path.exists(project_root):
            return None

        # 1. grep 快速定位候选文件
        candidate_files = self._grep_candidates(func_name, project_root)
        if not candidate_files:
            logging.debug(f"grep found no candidates for {func_name}")
            return None

        # 2. 排序：头文件优先，当前目录优先
        current_dir = os.path.dirname(current_file_path) if current_file_path else ""

        def sort_key(fp):
            rel = os.path.relpath(fp, project_root)
            is_header = 0 if fp.endswith(('.h', '.hpp')) else 1
            same_dir = 0 if rel.startswith(current_dir) else 1
            return (is_header, same_dir, rel)

        candidate_files.sort(key=sort_key)

        # 3. 逐一解析
        for file_path in candidate_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    file_content = f.read()

                lines = file_content.split('\n')
                source_lines = {i + 1: line + '\n' for i, line in enumerate(lines)}

                definition = self._find_function_definition(
                    file_content, source_lines, func_name, set()
                )
                if definition:
                    rel_path = os.path.relpath(file_path, project_root)
                    definition['file_path'] = rel_path
                    logging.info(f"Found {func_name} in {rel_path}")
                    return definition

            except Exception as e:
                logging.debug(f"Error searching {file_path}: {e}")
                continue

        logging.debug(f"Function {func_name} not found in project")
        return None

    def _grep_candidates(self, func_name: str, project_root: str) -> List[str]:
        """用 grep 在整个项目目录中快速找到包含 func_name( 的 C/C++ 文件列表。"""
        pattern = rf'\b{re.escape(func_name)}\s*\('
        try:
            result = subprocess.run(
                [
                    'grep', '-rl',
                    '--include=*.c', '--include=*.h',
                    '--include=*.cpp', '--include=*.hpp',
                    '-E', pattern,
                    project_root
                ],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode not in (0, 1):
                logging.debug(f"grep error: {result.stderr}")
                return []
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logging.debug(f"grep failed: {e}")
            return []
    
    def _find_function_definition(
        self,
        full_code: str,
        source_lines: Dict[int, str],
        func_name: str,
        exclude_lines: Set[int]
    ) -> Optional[Dict]:
        """
        查找函数定义
        
        Args:
            full_code: 完整源代码
            source_lines: 行号 -> 代码行的字典
            func_name: 函数名
            exclude_lines: 要排除的行号集合
            
        Returns:
            {start_line, end_line, code, lines} 或 None
        """
        # 函数定义的正则表达式 - 支持多种格式
        # 1. 标准格式: return_type func_name(args) {
        # 2. 分行格式: return_type\nfunc_name(args)\n{
        # 3. 宏定义格式: #define func_name(args) ...
        
        patterns = [
            # 标准格式：return_type func_name(args) {
            re.compile(
                rf'\b([a-zA-Z_][a-zA-Z0-9_*\s]*)\s+{re.escape(func_name)}\s*\([^)]*\)\s*{{',
                re.MULTILINE | re.DOTALL
            ),
            # 分行格式：func_name可能在新行
            re.compile(
                rf'^{re.escape(func_name)}\s*\([^)]*\)\s*{{',
                re.MULTILINE
            ),
            # 宏定义格式
            re.compile(
                rf'^\s*#\s*define\s+{re.escape(func_name)}\s*\([^)]*\)',
                re.MULTILINE
            ),
            # 头文件声明格式（无函数体，可能带属性宏）：return_type func_name(args) [attrs];
            re.compile(
                rf'\b([a-zA-Z_][a-zA-Z0-9_*\s]*)\s+\*?{re.escape(func_name)}\s*\([^)]*\)[^;{{]*;',
                re.MULTILINE
            ),
        ]
        
        match = None
        matched_pattern_idx = -1
        for idx, pattern in enumerate(patterns):
            match = pattern.search(full_code)
            if match:
                matched_pattern_idx = idx
                break
        
        if not match:
            logging.debug(f"Function definition not found: {func_name}")
            return None
        
        # 头文件声明（最后一个 pattern）：提取单行声明，不尝试匹配花括号
        if matched_pattern_idx == len(patterns) - 1 and '{' not in match.group(0):
            func_start_pos = match.start()
            lines_before = full_code[:func_start_pos].count('\n')
            start_line = min(source_lines.keys()) + lines_before
            end_line = start_line  # 声明通常是单行
            # 若声明跨行（换行符在 match 内）
            end_line = start_line + match.group(0).count('\n')
            
            func_lines = set(range(start_line, end_line + 1))
            if func_lines & exclude_lines:
                logging.debug(f"Declaration {func_name} overlaps with current function, skipping")
                return None
            
            decl_code_lines = []
            for line_num in range(start_line, end_line + 1):
                if line_num in source_lines:
                    decl_code_lines.append(source_lines[line_num])
            
            return {
                "start_line": start_line,
                "end_line": end_line,
                "code": "".join(decl_code_lines),
                "lines": sorted(func_lines),
                "is_macro": False
            }
        
        # 检查是否是宏定义
        is_macro = '#define' in match.group(0)
        
        if is_macro:
            # 宏定义：提取到行尾或续行符
            func_start_pos = match.start()
            lines_before = full_code[:func_start_pos].count('\n')
            start_line = min(source_lines.keys()) + lines_before
            
            # 查找宏定义的结束（可能有反斜杠续行）
            end_pos = match.end()
            while end_pos < len(full_code):
                if full_code[end_pos] == '\n':
                    # 检查前一个非空白字符是否是反斜杠
                    i = end_pos - 1
                    while i >= 0 and full_code[i] in ' \t':
                        i -= 1
                    if i >= 0 and full_code[i] == '\\':
                        # 续行，继续查找
                        end_pos += 1
                        continue
                    else:
                        # 宏定义结束
                        break
                end_pos += 1
            
            lines_in_macro = full_code[:end_pos].count('\n') - lines_before
            end_line = start_line + lines_in_macro
            
            # 提取宏代码
            macro_code_lines = []
            for line_num in range(start_line, end_line + 1):
                if line_num in source_lines:
                    macro_code_lines.append(source_lines[line_num])
            
            return {
                "start_line": start_line,
                "end_line": end_line,
                "code": "".join(macro_code_lines),
                "lines": sorted(range(start_line, end_line + 1)),
                "is_macro": True
            }
        
        # 找到函数开始位置
        func_start_pos = match.start()
        
        # 计算起始行号
        lines_before = full_code[:func_start_pos].count('\n')
        start_line = min(source_lines.keys()) + lines_before
        
        # 查找函数结束位置（匹配大括号）
        brace_pos = full_code.find('{', func_start_pos)
        if brace_pos == -1:
            logging.debug(f"Could not find opening brace for function: {func_name}")
            return None
            
        end_line = self._find_function_end_line(
            full_code, 
            brace_pos,
            source_lines
        )
        
        if not end_line:
            logging.debug(f"Could not find end of function: {func_name}")
            return None
        
        # 检查是否与当前函数重叠
        func_lines = set(range(start_line, end_line + 1))
        if func_lines & exclude_lines:
            logging.debug(f"Function {func_name} overlaps with current function, skipping")
            return None
        
        # 提取函数代码
        func_code_lines = []
        for line_num in range(start_line, end_line + 1):
            if line_num in source_lines:
                func_code_lines.append(source_lines[line_num])
        
        return {
            "start_line": start_line,
            "end_line": end_line,
            "code": "".join(func_code_lines),
            "lines": sorted(func_lines),
            "is_macro": False
        }
    
    def _find_function_end_line(
        self, 
        full_code: str, 
        start_pos: int,
        source_lines: Dict[int, str]
    ) -> Optional[int]:
        """
        查找函数结束行（通过匹配大括号）
        
        Args:
            full_code: 完整源代码
            start_pos: 起始大括号的位置
            source_lines: 行号 -> 代码行的字典
            
        Returns:
            结束行号或 None
        """
        brace_count = 1
        i = start_pos + 1
        
        while i < len(full_code) and brace_count > 0:
            if full_code[i] == '{':
                brace_count += 1
            elif full_code[i] == '}':
                brace_count -= 1
            i += 1
        
        if brace_count == 0:
            # 计算结束行号
            lines_before = full_code[:i].count('\n')
            end_line = min(source_lines.keys()) + lines_before
            return end_line
        
        return None


def extract_called_functions(
    sliced_code: str,
    source_lines: Dict[int, str],
    slice_lines: Set[int],
    function_start_line: int = None,
    function_end_line: int = None,
    project_root: str = None,
    current_file_path: str = None
) -> Tuple[Dict[str, Dict], Set[str]]:
    """
    从切片代码中提取所有被调用函数的完整定义
    
    Args:
        sliced_code: 切片后的代码
        source_lines: 完整源文件的行号 -> 代码行字典
        slice_lines: 切片包含的行号集合
        function_start_line: 当前函数的起始行（避免重复提取）
        function_end_line: 当前函数的结束行（避免重复提取）
        project_root: 项目根目录（用于跨文件搜索）
        current_file_path: 当前文件的相对路径
        
    Returns:
        (函数定义字典, 函数调用集合)
    """
    extractor = FunctionCallExtractor()
    
    # 提取函数调用
    function_calls = extractor.extract_function_calls(sliced_code)
    
    if not function_calls:
        return {}, set()
    
    logging.info(f"Found {len(function_calls)} function calls: {function_calls}")
    
    # 确定当前函数的行号范围
    current_func_lines = set()
    if function_start_line and function_end_line:
        current_func_lines = set(range(function_start_line, function_end_line + 1))
    
    # 提取函数定义（支持项目级搜索）
    function_definitions = extractor.extract_function_definitions_from_file(
        source_lines,
        function_calls,
        current_func_lines,
        project_root,
        current_file_path
    )
    
    logging.info(f"Extracted {len(function_definitions)} function definitions")
    
    return function_definitions, function_calls

"""
基于 Tree-sitter 的函数提取器
使用 Tree-sitter 解析 C/C++ 代码，准确提取函数定义和宏定义
"""
import os
import re
import subprocess
import logging
from typing import Dict, List, Set, Tuple, Optional

try:
    from tree_sitter import Parser
    from tree_sitter_languages import get_language
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logging.warning("tree-sitter not available, install with: pip install tree-sitter tree-sitter-c")


class TreeSitterFunctionExtractor:
    """基于 Tree-sitter 的函数提取器"""
    
    def __init__(self):
        if not TREE_SITTER_AVAILABLE:
            raise RuntimeError("tree-sitter is not available")
        
        # 初始化 C 语言解析器
        try:
            lang_obj = get_language("c")
            self.parser = Parser()
            self.parser.set_language(lang_obj)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize parser for c: {e}")
        
        # C/C++ 关键字和标准库函数
        self.c_keywords = {
            'if', 'else', 'while', 'for', 'do', 'switch', 'case', 'default',
            'break', 'continue', 'return', 'goto', 'sizeof', 'typeof',
            'static_cast', 'dynamic_cast', 'reinterpret_cast', 'const_cast',
            '__attribute__', '__builtin_expect', 'offsetof'
        }
        
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
        # 将代码转换为字节
        source_bytes = bytes(code, 'utf8')
        
        # 解析代码 - 新版本 API
        tree = self.parser.parse(source_bytes)
        root = tree.root_node
        
        function_calls = set()
        
        # 遍历所有 call_expression 节点
        self._extract_calls_recursive(root, function_calls, source_bytes)
        
        # 过滤关键字和标准库函数
        filtered_calls = {
            name for name in function_calls
            if name not in self.c_keywords and name not in self.stdlib_functions
        }
        
        return filtered_calls
    
    def _extract_calls_recursive(self, node, calls: Set[str], source_code: bytes):
        """递归提取函数调用"""
        if node.type == 'call_expression':
            # 获取被调用的函数名
            function_node = node.child_by_field_name('function')
            if function_node:
                func_name = source_code[function_node.start_byte:function_node.end_byte].decode('utf8')
                # 只提取简单的标识符（不包括成员访问等）
                if function_node.type == 'identifier':
                    calls.add(func_name)
        
        # 递归处理子节点
        for child in node.children:
            self._extract_calls_recursive(child, calls, source_code)
    
    def extract_function_definition(
        self,
        code: str,
        func_name: str,
        file_path: str = None
    ) -> Optional[Dict]:
        """
        从代码中提取指定函数的定义
        
        Args:
            code: 源代码字符串
            func_name: 函数名
            file_path: 文件路径（用于相对路径）
            
        Returns:
            {start_line, end_line, code, lines, is_macro, file_path} 或 None
        """
        source_bytes = bytes(code, 'utf8')
        tree = self.parser.parse(source_bytes)
        root = tree.root_node
        
        # 先查找函数定义（有函数体）
        func_def = self._find_function_definition(root, func_name, source_bytes, code)
        if func_def:
            func_def['file_path'] = file_path or 'unknown'
            func_def['is_macro'] = False
            return func_def
        
        # 如果没找到函数定义，查找函数声明（如头文件中的 declaration）
        decl_def = self._find_function_declaration(root, func_name, source_bytes, code)
        if decl_def:
            decl_def['file_path'] = file_path or 'unknown'
            decl_def['is_macro'] = False
            return decl_def
        
        # 如果没找到函数，查找宏定义
        macro_def = self._find_macro_definition(root, func_name, source_bytes, code)
        if macro_def:
            macro_def['file_path'] = file_path or 'unknown'
            macro_def['is_macro'] = True
            return macro_def
        
        return None
    
    def _find_function_declaration(
        self,
        node,
        func_name: str,
        source_bytes: bytes,
        code: str
    ) -> Optional[Dict]:
        """查找函数声明（头文件中无函数体的声明，如 void *av_mallocz(size_t) av_attr;）。
        
        tree-sitter 有时会将带属性宏的声明拆成多个 declaration 节点，
        因此找到目标节点后，从原始文本中按行提取完整声明（直到含 ; 的行）。
        """
        if node.type == 'declaration':
            for child in node.children:
                actual_name = self._get_function_name(child, source_bytes)
                if actual_name == func_name:
                    start_line = node.start_point[0] + 1  # 1-based
                    
                    # 从原始代码按行提取，合并到出现 ';' 为止（处理属性宏跨节点问题）
                    lines = code.splitlines()
                    end_line = start_line
                    collected = []
                    for i in range(start_line - 1, len(lines)):
                        collected.append(lines[i])
                        end_line = i + 1  # 1-based
                        if ';' in lines[i]:
                            break
                    
                    decl_code = '\n'.join(collected)
                    return {
                        'start_line': start_line,
                        'end_line': end_line,
                        'code': decl_code,
                        'lines': list(range(start_line, end_line + 1))
                    }
        
        # 递归搜索子节点
        for child in node.children:
            result = self._find_function_declaration(child, func_name, source_bytes, code)
            if result:
                return result
        
        return None

    def _find_function_definition(
        self,
        node,
        func_name: str,
        source_bytes: bytes,
        code: str
    ) -> Optional[Dict]:
        """查找函数定义"""
        if node.type == 'function_definition':
            # 获取函数声明器
            declarator = node.child_by_field_name('declarator')
            if declarator:
                # 提取函数名
                actual_name = self._get_function_name(declarator, source_bytes)
                if actual_name == func_name:
                    # 找到了！提取信息
                    start_line = node.start_point[0] + 1  # tree-sitter 行号从0开始
                    end_line = node.end_point[0] + 1
                    
                    func_code = source_bytes[node.start_byte:node.end_byte].decode('utf8')
                    
                    return {
                        'start_line': start_line,
                        'end_line': end_line,
                        'code': func_code,
                        'lines': list(range(start_line, end_line + 1))
                    }
        
        # 递归搜索子节点
        for child in node.children:
            result = self._find_function_definition(child, func_name, source_bytes, code)
            if result:
                return result
        
        return None
    
    def _find_macro_definition(
        self,
        node,
        macro_name: str,
        source_bytes: bytes,
        code: str
    ) -> Optional[Dict]:
        """查找宏定义"""
        if node.type == 'preproc_function_def':
            # 获取宏名称
            name_node = node.child_by_field_name('name')
            if name_node:
                actual_name = source_bytes[name_node.start_byte:name_node.end_byte].decode('utf8')
                if actual_name == macro_name:
                    start_line = node.start_point[0] + 1
                    end_line = node.end_point[0] + 1
                    
                    macro_code = source_bytes[node.start_byte:node.end_byte].decode('utf8')
                    
                    return {
                        'start_line': start_line,
                        'end_line': end_line,
                        'code': macro_code,
                        'lines': list(range(start_line, end_line + 1))
                    }
        
        # 递归搜索子节点
        for child in node.children:
            result = self._find_macro_definition(child, macro_name, source_bytes, code)
            if result:
                return result
        
        return None
    
    def _get_function_name(self, declarator, source_bytes: bytes) -> Optional[str]:
        """从声明器中提取函数名"""
        # 处理不同类型的声明器
        if declarator.type == 'function_declarator':
            # 获取内部声明器
            inner = declarator.child_by_field_name('declarator')
            if inner:
                return self._get_function_name(inner, source_bytes)
        elif declarator.type == 'pointer_declarator':
            # 指针声明器，继续向内查找
            inner = declarator.child_by_field_name('declarator')
            if inner:
                return self._get_function_name(inner, source_bytes)
        elif declarator.type == 'identifier':
            # 找到标识符
            return source_bytes[declarator.start_byte:declarator.end_byte].decode('utf8')
        
        return None
    
    def search_function_in_project(
        self,
        func_name: str,
        project_root: str,
        current_file_path: str = None,
        max_files: int = 400
    ) -> Optional[Dict]:
        """
        在项目中搜索函数定义/声明。
        
        策略：先用 grep 在整个项目中快速定位包含 func_name 的文件，
        再用 tree-sitter 精确解析候选文件，避免文件数量限制问题。
        优先搜索头文件（.h/.hpp），其次源文件（.c/.cpp）。
        """
        if not os.path.exists(project_root):
            logging.debug(f"Project root does not exist: {project_root}")
            return None

        # ------------------------------------------------------------------
        # 1. 用 grep 快速找到包含 func_name 的候选文件
        # ------------------------------------------------------------------
        candidate_files = self._grep_candidates(func_name, project_root)
        if not candidate_files:
            logging.debug(f"grep found no candidates for {func_name} in {project_root}")
            return None

        logging.debug(f"grep found {len(candidate_files)} candidate files for {func_name}")

        # ------------------------------------------------------------------
        # 2. 排序：当前目录优先；同目录下源文件（.c/.cpp）排在头文件前面，
        #    以便尽早找到完整实现；其他目录的头文件排在后面作为兜底
        # ------------------------------------------------------------------
        current_dir = os.path.dirname(current_file_path) if current_file_path else ""

        def sort_key(fp):
            rel = os.path.relpath(fp, project_root)
            same_dir = 0 if rel.startswith(current_dir) else 1
            # 同目录下：源文件（实现）优先；其他目录：头文件优先（作为兜底声明）
            if same_dir == 0:
                is_impl = 0 if fp.endswith(('.c', '.cpp')) else 1
            else:
                is_impl = 0 if fp.endswith(('.h', '.hpp')) else 1
            return (same_dir, is_impl, rel)

        candidate_files.sort(key=sort_key)

        # ------------------------------------------------------------------
        # 3. 逐一用 tree-sitter 解析：
        #    - 优先找有函数体的完整实现（function_definition）
        #    - 如果只找到声明（declaration），暂存后继续，
        #      待全部候选文件搜完仍无实现时再使用声明作为兜底
        # ------------------------------------------------------------------
        best_decl: Optional[Dict] = None  # 暂存首个声明（兜底用）

        for file_path in candidate_files:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    code = f.read()
                rel_path = os.path.relpath(file_path, project_root)

                source_bytes = bytes(code, 'utf8')
                tree = self.parser.parse(source_bytes)
                root = tree.root_node

                # 先尝试找完整实现（function_definition）
                func_def = self._find_function_definition(root, func_name, source_bytes, code)
                if func_def:
                    func_def['file_path'] = rel_path
                    func_def['is_macro'] = False
                    logging.info(f"Found implementation of {func_name} in {rel_path}")
                    return func_def

                # 找宏定义（实现级别，直接返回）
                macro_def = self._find_macro_definition(root, func_name, source_bytes, code)
                if macro_def:
                    macro_def['file_path'] = rel_path
                    macro_def['is_macro'] = True
                    logging.info(f"Found macro {func_name} in {rel_path}")
                    return macro_def

                # 找到声明则暂存（不立即返回）
                if best_decl is None:
                    decl_def = self._find_function_declaration(root, func_name, source_bytes, code)
                    if decl_def:
                        decl_def['file_path'] = rel_path
                        decl_def['is_macro'] = False
                        best_decl = decl_def
                        logging.debug(f"Found declaration of {func_name} in {rel_path}, continuing search for implementation")

            except Exception as e:
                logging.debug(f"Error parsing {file_path}: {e}")
                continue

        # 全部候选文件搜完，仍无实现，使用声明作为兜底
        if best_decl:
            logging.info(f"No implementation found for {func_name}, using declaration from {best_decl['file_path']}")
            return best_decl

        logging.debug(f"Function {func_name} not found in project")
        return None

    def _grep_candidates(self, func_name: str, project_root: str) -> List[str]:
        """
        用 grep 在项目目录中快速找到包含 func_name 的 C/C++ 文件列表。
        同时匹配函数定义（有 {）和函数声明（有 ;），覆盖头文件中的声明。
        """
        # 匹配模式：func_name 后紧跟 ( 的行，排除纯注释行
        pattern = rf'\b{re.escape(func_name)}\s*\('
        try:
            result = subprocess.run(
                [
                    'grep', '-rl',          # 递归，只输出文件名
                    '--include=*.c',
                    '--include=*.h',
                    '--include=*.cpp',
                    '--include=*.hpp',
                    '-E', pattern,
                    project_root
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode not in (0, 1):  # 1 = no match，其他为错误
                logging.debug(f"grep error: {result.stderr}")
                return []
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return files
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logging.debug(f"grep failed: {e}, falling back to file walk")
            return self._collect_search_files(project_root, None, max_files=9999)
    
    def _collect_search_files(
        self,
        project_root: str,
        current_file_path: str,
        max_files: int
    ) -> List[str]:
        """收集要搜索的源文件列表（按优先级排序）。
        
        策略：
          1. 当前文件对应的头文件（最高优先级）
          2. 当前目录下的所有头文件
          3. 项目所有子目录下的头文件（.h/.hpp），按目录名字母序
          4. 项目所有子目录下的源文件（.c/.cpp），按目录名字母序
        
        将头文件与源文件分开两轮收集，确保头文件不会被大量 .c 文件挤出配额。
        """
        seen = set()
        search_files = []

        def add(path):
            if path not in seen and os.path.isfile(path):
                seen.add(path)
                search_files.append(path)

        # ------------------------------------------------------------------
        # 1. 当前文件同名头文件
        # ------------------------------------------------------------------
        if current_file_path:
            current_dir = os.path.dirname(current_file_path)
            current_base = os.path.splitext(os.path.basename(current_file_path))[0]
            for ext in ['.h', '.hpp']:
                add(os.path.join(project_root, current_dir, current_base + ext))

        # ------------------------------------------------------------------
        # 2. 当前目录下所有头文件 & 源文件
        # ------------------------------------------------------------------
        if current_file_path:
            cur_dir_abs = os.path.join(project_root, os.path.dirname(current_file_path))
            if os.path.exists(cur_dir_abs):
                for filename in sorted(os.listdir(cur_dir_abs)):
                    if filename.endswith(('.h', '.hpp', '.c', '.cpp')):
                        add(os.path.join(cur_dir_abs, filename))

        # ------------------------------------------------------------------
        # 3. 收集项目下所有候选目录（固定 + lib* 动态目录）
        # ------------------------------------------------------------------
        candidate_dirs = []
        fixed = ['src', 'include', 'lib']
        if os.path.exists(project_root):
            for entry in sorted(os.listdir(project_root)):
                full = os.path.join(project_root, entry)
                if not os.path.isdir(full):
                    continue
                if entry in fixed or entry.startswith('lib'):
                    candidate_dirs.append(full)
            # 固定目录也加上
            for s in fixed:
                full = os.path.join(project_root, s)
                if os.path.isdir(full) and full not in candidate_dirs:
                    candidate_dirs.insert(0, full)

        def collect_from_dirs(extensions):
            """从 candidate_dirs 中收集指定扩展名的文件"""
            for search_dir in candidate_dirs:
                dir_files = []
                for root, dirs, files in os.walk(search_dir):
                    dirs.sort()
                    for filename in sorted(files):
                        if filename.endswith(extensions):
                            dir_files.append(os.path.join(root, filename))
                for fp in dir_files:
                    add(fp)
                    if len(search_files) >= max_files:
                        return True  # 已满
            return False

        # ------------------------------------------------------------------
        # 4. 第一轮：仅收集头文件（覆盖所有目录）
        # ------------------------------------------------------------------
        if len(search_files) < max_files:
            if collect_from_dirs(('.h', '.hpp')):
                return search_files[:max_files]

        # ------------------------------------------------------------------
        # 5. 第二轮：收集源文件（剩余配额）
        # ------------------------------------------------------------------
        if len(search_files) < max_files:
            collect_from_dirs(('.c', '.cpp'))

        return search_files[:max_files]


def extract_called_functions_treesitter(
    sliced_code: str,
    project_root: str,
    current_file_path: str = None,
    current_file_code: str = None
) -> Tuple[Dict[str, Dict], Set[str]]:
    """
    使用 Tree-sitter 提取被调用函数的定义
    
    Args:
        sliced_code: 切片代码
        project_root: 项目根目录
        current_file_path: 当前文件的相对路径
        current_file_code: 当前文件的完整代码（优先在当前文件中查找）
        
    Returns:
        (函数定义字典, 函数调用集合)
    """
    if not TREE_SITTER_AVAILABLE:
        logging.warning("Tree-sitter not available, skipping function extraction")
        return {}, set()
    
    try:
        extractor = TreeSitterFunctionExtractor()
        
        # 提取函数调用
        function_calls = extractor.extract_function_calls(sliced_code)
        
        if not function_calls:
            return {}, set()
        
        logging.info(f"Found {len(function_calls)} function calls: {function_calls}")
        
        function_definitions = {}
        
        # 对每个函数调用，尝试提取定义
        for func_name in function_calls:
            # 首先在当前文件中查找
            if current_file_code:
                definition = extractor.extract_function_definition(
                    current_file_code,
                    func_name,
                    'current'
                )
                if definition:
                    function_definitions[func_name] = definition
                    continue
            
            # 如果当前文件没找到，在整个项目中搜索
            if project_root:
                definition = extractor.search_function_in_project(
                    func_name,
                    project_root,
                    current_file_path
                )
                if definition:
                    function_definitions[func_name] = definition
        
        logging.info(f"Extracted {len(function_definitions)} function definitions using tree-sitter")
        
        return function_definitions, function_calls
        
    except Exception as e:
        logging.error(f"Tree-sitter extraction failed: {e}")
        import traceback
        logging.debug(traceback.format_exc())
        return {}, set()

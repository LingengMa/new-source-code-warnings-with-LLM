"""
AST 增强模块
使用 tree-sitter 补充语法结构，确保切片代码语法正确
"""
from typing import Set, List, Dict, Optional
import logging
import re

try:
    from tree_sitter import Parser, Node
    from tree_sitter_languages import get_language
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
    logging.warning("tree-sitter not available, AST enhancement disabled")


class ASTEnhancer:
    """AST 增强器"""
    
    def __init__(self, language: str = "c"):
        self.language = language
        
        if not TREE_SITTER_AVAILABLE:
            raise RuntimeError("tree-sitter is required for AST enhancement")
        
        # 使用 tree-sitter-languages 简化的 API
        try:
            lang_obj = get_language(language)
            self.parser = Parser()
            self.parser.set_language(lang_obj)
            logging.info(f"ASTEnhancer initialized for language: {language}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize parser for {language}: {e}")
    
    def enhance_slice(self, 
                     source_code: str, 
                     slice_lines: Set[int],
                     function_start_line: int = 1,
                     target_line: Optional[int] = None) -> Set[int]:
        """
        增强切片，补充必要的语法结构。

        当 source_code 包含多个函数（如 <global> 场景下传入整个文件）时，
        会对切片中每个函数分别做 AST 增强，确保所有 for/if/while/switch 语句
        的 {} 括号都被补全。

        关键增强：若 target_line 落在某个 if/else 分支内，强制将该分支所在的
        完整 if-else 结构（含所有兄弟分支的括号和头部）纳入切片，
        防止切片代码进入错误的控制流分支。

        Args:
            source_code: 完整的源代码（可以是单函数或多函数文件）
            slice_lines: 切片行号集合（绝对行号）
            function_start_line: source_code 在原始文件中的起始行号（用于行号偏移）
            target_line: 警告行的绝对行号（传入后会强制保留其所在 if-else 完整结构）
        
        Returns:
            增强后的行号集合
        """
        if not slice_lines:
            return slice_lines
        
        # 解析 AST
        src_bytes_val = bytes(source_code, "utf8")
        tree = self.parser.parse(src_bytes_val)
        root = tree.root_node
        # 保存字节串供子方法（_anchor_null_checks_after_assignments）使用
        self._cur_src_bytes = src_bytes_val

        # 收集源码中所有顶层 function_definition 节点
        all_funcs = self._collect_all_functions(root)

        if not all_funcs:
            logging.warning(f"No function nodes found in parsed tree (root type: {root.type})")
            return slice_lines

        # 转换为相对行号（相对于 source_code 的第1行）
        rel_slice_lines = {line - function_start_line + 1 for line in slice_lines}
        # 目标行的相对行号（用于强制补全包含目标行的 if-else 结构）
        target_rel: Optional[int] = (
            target_line - function_start_line + 1
            if target_line is not None else None
        )

        enhanced_rel = set(rel_slice_lines)

        # 对每个函数分别做 AST 增强
        # 只处理「与当前切片有交集」的函数，避免无关函数干扰
        for func_node in all_funcs:
            func_start_rel = func_node.start_point[0] + 1  # 1-based 相对行
            func_end_rel   = func_node.end_point[0] + 1

            # 判断该函数是否与切片相交
            if not any(func_start_rel <= ln <= func_end_rel for ln in enhanced_rel):
                continue

            # 提取该函数内的相对切片行（仅该函数范围内的行）
            func_rel_lines = {ln for ln in enhanced_rel if func_start_rel <= ln <= func_end_rel}

            body_node = func_node.child_by_field_name("body")
            if not body_node:
                continue

            logging.debug(
                f"AST enhancing function at rel lines {func_start_rel}-{func_end_rel}, "
                f"slice has {len(func_rel_lines)} lines in this function"
            )

            # 0. 若目标行在此函数内，先强制补全其所在的所有祖先 if-else 块，
            #    确保目标行的结构上下文被完整保留
            if target_rel is not None and func_start_rel <= target_rel <= func_end_rel:
                func_rel_lines = self._anchor_target_in_if_blocks(
                    body_node, func_rel_lines, target_rel
                )

            # 0b. 补全切片中每条赋值语句紧随其后的 NULL / 错误检查块
            #     （如 ptr = malloc(...); if (ptr == NULL) { ... }）
            func_rel_lines = self._anchor_null_checks_after_assignments(
                body_node, func_rel_lines
            )

            # 0c. 补全分配操作前的 free 操作
            #     （如 OPENSSL_free(ptr); ptr = malloc(...) 这种先释放再分配模式）
            #     对 use-after-free 分析至关重要：free 是内存生命周期的起点
            func_rel_lines = self._anchor_free_before_alloc(
                body_node, func_rel_lines
            )

            # 1. 补全函数签名（含函数体首尾 {}）
            func_enhanced = self._complete_function_signature(func_node, func_rel_lines)

            # 2. 递归处理所有控制流结构，确保语法块闭合
            func_enhanced = self._ast_dive_c(body_node, func_enhanced, 1)

            # 3. 补全控制流终止语句（break / continue / return / goto）
            func_enhanced = self._ast_add(body_node, func_enhanced, 1)

            # 4. 修剪：移除空 else / 空 case 等无意义残留
            func_enhanced = self._ast_trim(body_node, func_enhanced, 1)

            # 合并回总集合：
            # 不能直接用 |=，因为 _ast_trim 可能删除了 enhanced_rel 里原有的行（游离的 }）。
            # 正确做法：先移除该函数行范围内所有原有行，再合并 func_enhanced 的结果。
            enhanced_rel = {
                ln for ln in enhanced_rel
                if not (func_start_rel <= ln <= func_end_rel)
            } | func_enhanced

        # 转换回绝对行号
        abs_enhanced_lines = {line + function_start_line - 1 for line in enhanced_rel}
        
        logging.info(f"AST enhancement: {len(slice_lines)} -> {len(abs_enhanced_lines)} lines")
        
        return abs_enhanced_lines
    
    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _node_lines(self, node: Node) -> Set[int]:
        """返回节点所有行（1-based，相对于传入的源码）"""
        return set(range(node.start_point[0] + 1, node.end_point[0] + 2))

    def _node_start(self, node: Node) -> int:
        return node.start_point[0] + 1

    def _node_end(self, node: Node) -> int:
        return node.end_point[0] + 1

    def _intersects(self, node: Node, slice_lines: Set[int]) -> bool:
        """节点行范围是否与切片行集合相交"""
        start = self._node_start(node)
        end = self._node_end(node)
        return any(start <= ln <= end for ln in slice_lines)

    def _add_node_header(self, node: Node, enhanced: Set[int]) -> Set[int]:
        """
        将节点"头部"（从节点第一行到函数体开始行，或者整个单行头部）加入切片。
        用于 for/while/switch/if 等控制语句：确保括号行、条件行全部包含。
        对于函数体节点（compound_statement），只添加开括号行和闭括号行。
        """
        enhanced = enhanced.copy()
        if node.type == "compound_statement":
            enhanced.add(self._node_start(node))  # {
            enhanced.add(self._node_end(node))    # }
            return enhanced

        # 控制语句：添加从语句开始到其 body/consequence/... 的 { 之间的所有行
        body = (node.child_by_field_name("body") or
                node.child_by_field_name("consequence"))
        if body:
            header_end = self._node_start(body)  # body 的第一行（即 {）
        else:
            header_end = self._node_start(node)

        for ln in range(self._node_start(node), header_end + 1):
            enhanced.add(ln)
        return enhanced

    def _find_function_node(self, root: Node, target_line: int) -> Optional[Node]:
        """查找包含目标行的函数节点"""
        
        def _search(node: Node) -> Optional[Node]:
            if node.type == "function_definition":
                start_line = node.start_point[0] + 1
                end_line = node.end_point[0] + 1
                if start_line <= target_line <= end_line:
                    return node
            
            for child in node.children:
                result = _search(child)
                if result:
                    return result
            
            return None
        
        return _search(root)

    def _collect_all_functions(self, root: Node) -> list:
        """
        收集 AST 中所有的 function_definition 节点（不限层级）。
        用于多函数源码场景（如 <global> PDG 覆盖整个文件时）。
        """
        funcs = []

        def _walk(node: Node):
            if node.type == "function_definition":
                funcs.append(node)
                # 不再递归进函数内部（避免嵌套函数重复处理）
                return
            for child in node.children:
                _walk(child)

        _walk(root)
        return funcs

    def _anchor_target_in_if_blocks(
        self,
        body_node: Node,
        slice_lines: Set[int],
        target_rel: int,
    ) -> Set[int]:
        """
        强制将目标行所在的所有祖先 if-else 结构完整纳入切片。

        问题背景：
            PDG 切片只沿数据/控制依赖传播。若目标行（警告行）位于某个
            if-else 的某一分支内，PDG 往往只选中了该行本身，而丢失了：
              a. 包裹该行的 if (...) { 头部
              b. 目标行所在分支的完整内容（含 length = 0 等同分支语句）
              c. 兄弟分支（consequence / other else）的括号行

            若只补括号行（{ 和 }）而不补内容，_ast_trim 会因兄弟分支
            "内部为空"而将整个 if 结构删除，导致目标行的上下文彻底消失。

        策略：
            对于包含 target_rel 的每一层 if_statement：
            1. 补全 if (...) { 头部；
            2. 找出 target_rel 所在的分支（consequence 或 alternative），
               将该分支的**全部行**纳入切片；
            3. 对兄弟分支只补括号行（{ 和 }），使结构合法但内容最小化；
            4. 递归处理嵌套 if / else if。

        Args:
            body_node: 当前函数/复合语句的 body 节点（compound_statement）
            slice_lines: 当前相对行号集合
            target_rel: 目标行的相对行号（1-based，相对于传入 source_code 的第1行）

        Returns:
            补全后的相对行号集合
        """
        enhanced = slice_lines.copy()

        def _contains_target(node: Node) -> bool:
            return self._node_start(node) <= target_rel <= self._node_end(node)

        def _add_all_lines(node: Node):
            """将节点所有行加入切片"""
            for ln in range(self._node_start(node), self._node_end(node) + 1):
                enhanced.add(ln)

        def _add_braces_only(node: Node):
            """只添加 compound_statement 的 { 和 } 行（最小化兄弟分支）"""
            if node is None:
                return
            if node.type == "compound_statement":
                enhanced.add(self._node_start(node))
                enhanced.add(self._node_end(node))
            elif node.type == "else_clause":
                enhanced.add(self._node_start(node))  # else 关键字行
                comp = self._get_body_compound(node)
                if comp is not None:
                    enhanced.add(self._node_start(comp))
                    enhanced.add(self._node_end(comp))
                else:
                    enhanced.add(self._node_end(node))
            else:
                # 单语句体，直接加整行
                enhanced.add(self._node_start(node))
                enhanced.add(self._node_end(node))

        def _walk(node: Node):
            nonlocal enhanced
            if not node.is_named:
                return

            if node.type == "if_statement" and _contains_target(node):
                consequence = node.child_by_field_name("consequence")
                alternative = node.child_by_field_name("alternative")

                # 1. 补全 if (...) { 头部
                enhanced = self._add_full_header(node, enhanced)

                # 2. 确定目标行在哪个分支
                target_in_cons = (consequence is not None and
                                  self._node_start(consequence) <= target_rel <= self._node_end(consequence))
                target_in_alt  = (alternative is not None and
                                  self._node_start(alternative) <= target_rel <= self._node_end(alternative))

                if target_in_cons:
                    # 目标在 consequence：consequence 全量，alternative 只补括号
                    if consequence is not None:
                        _add_all_lines(consequence)
                    if alternative is not None:
                        _add_braces_only(alternative)
                elif target_in_alt:
                    # 目标在 alternative：alternative 全量，consequence 只补括号
                    if consequence is not None:
                        _add_braces_only(consequence)
                    if alternative is not None:
                        if alternative.type == "if_statement":
                            # else if：只加 else if 头部，递归会处理内部
                            enhanced = self._add_full_header(alternative, enhanced)
                        else:
                            _add_all_lines(alternative)
                else:
                    # 目标行就在 if 头部条件行（极少情况），两个分支都只补括号
                    if consequence is not None:
                        _add_braces_only(consequence)
                    if alternative is not None:
                        _add_braces_only(alternative)

                logging.debug(
                    f"_anchor_target_in_if_blocks: anchored if at rel lines "
                    f"{self._node_start(node)}-{self._node_end(node)} "
                    f"(target_rel={target_rel}, in_cons={target_in_cons}, in_alt={target_in_alt})"
                )

            # 向子节点递归，处理嵌套 if / else if
            for child in node.children:
                _walk(child)

        for child in body_node.children:
            _walk(child)

        return enhanced

    # 匹配分配函数调用：malloc/calloc/realloc/OPENSSL_malloc/OPENSSL_memdup 等
    _ALLOC_CALL_RE = re.compile(
        r'\b(OPENSSL_malloc|OPENSSL_zalloc|OPENSSL_memdup|OPENSSL_strdup'
        r'|malloc|calloc|realloc|strdup|strndup|memdup'
        r'|g_malloc|g_new|PyMem_Malloc|zmalloc)\s*\('
    )

    # 匹配释放函数调用：free/OPENSSL_free/CRYPTO_free 等
    _FREE_CALL_RE = re.compile(
        r'\b(OPENSSL_free|CRYPTO_free|free|g_free|PyMem_Free|zfree)\s*\('
    )

    def _anchor_free_before_alloc(
        self,
        body_node: Node,
        slice_lines: Set[int],
    ) -> Set[int]:
        """
        对切片中每条「含分配函数调用的赋值语句」，向前查找紧邻的
        free/释放操作节点，将其纳入切片。

        背景：
            use-after-free 的典型模式是先 free 再 alloc：
                OPENSSL_free(s->s3.alpn_selected);          // 释放
                s->s3.alpn_selected = OPENSSL_malloc(len);  // 重新分配
            PDG 切片通常只选中 alloc 行（数据依赖起点），而忽略同一成员
            的 free 行。但 LLM 需要看到 free 才能判断内存是否存在 use-after-free。

            同时：若 alloc 行本身不在切片中，但切片中有该成员的后续使用，
            也通过文本匹配补入对应的 alloc + free 行。

        算法：
            遍历复合语句的直接子节点列表。
            对每个分配赋值节点 N（行在切片中）：
              向前查看最多 3 个兄弟节点，若某节点含 free 调用且操作同一成员
              变量（或同一末尾简单名），则将其纳入切片（单行，不展开块）。

        Args:
            body_node: 函数体复合语句节点
            slice_lines: 当前相对行号集合

        Returns:
            补全后的相对行号集合
        """
        enhanced = slice_lines.copy()
        src_bytes = getattr(self, '_cur_src_bytes', b'')
        if not src_bytes:
            return enhanced

        # 提取成员路径末尾简单名：s->s3.alpn_selected => alpn_selected
        def _leaf_name(path: str) -> str:
            return path.replace(' ', '').split('->')[-1].split('.')[-1]

        def _get_alloc_lhs(node: Node) -> Optional[str]:
            """提取分配赋值节点的完整左值路径（已规范化）"""
            code = src_bytes[node.start_byte:node.end_byte].decode('utf8', errors='replace')
            if not self._ALLOC_CALL_RE.search(code):
                return None
            matches = list(_LHS_FULL_RE.finditer(code))
            if not matches:
                return None
            return _normalize_lhs(matches[-1].group(1))

        def _free_matches_lhs(free_node: Node, lhs: str) -> bool:
            """判断 free 节点操作的是否是 lhs 指定的变量"""
            code = src_bytes[free_node.start_byte:free_node.end_byte].decode('utf8', errors='replace')
            if not self._FREE_CALL_RE.search(code):
                return False
            # 提取 free(...) 的参数（括号内部文本）
            m = re.search(r'(?:free|OPENSSL_free|CRYPTO_free|g_free|PyMem_Free|zfree)\s*\(\s*(.+?)\s*\)', code)
            if not m:
                return False
            arg = _normalize_lhs(m.group(1))
            lhs_leaf = _leaf_name(lhs)
            arg_leaf = _leaf_name(arg)
            # 精确全路径匹配，或末尾简单名匹配
            return arg == lhs or lhs_leaf == arg_leaf

        def _process_children(parent: Node):
            children = [c for c in parent.children if c.is_named]
            for idx, child in enumerate(children):
                # 该节点是否在切片中
                in_slice = any(
                    self._node_start(child) <= ln <= self._node_end(child)
                    for ln in enhanced
                )
                if not in_slice:
                    if child.type == 'compound_statement':
                        _process_children(child)
                    continue

                lhs = _get_alloc_lhs(child)
                if lhs is None:
                    if child.type == 'compound_statement':
                        _process_children(child)
                    continue

                # 向前查找紧邻兄弟节点（最多 3 个）中的 free 调用
                lookahead = 0
                for prev_child in reversed(children[:idx]):
                    if lookahead >= 3:
                        break
                    lookahead += 1
                    if _free_matches_lhs(prev_child, lhs):
                        before = len(enhanced)
                        for ln in range(self._node_start(prev_child),
                                        self._node_end(prev_child) + 1):
                            enhanced.add(ln)
                        added = len(enhanced) - before
                        if added:
                            logging.debug(
                                f"_anchor_free_before_alloc: added {added} lines for "
                                f"free of '{lhs}' at rel line {self._node_start(prev_child)}"
                            )
                        break  # 只取最近的一个 free

                if child.type == 'compound_statement':
                    _process_children(child)

        # 为本方法局部复用正则（与 _anchor_null_checks_after_assignments 保持一致）
        _LHS_FULL_RE = re.compile(
            r'((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)\s*=(?![>=])'
        )

        def _normalize_lhs(expr: str) -> str:
            return re.sub(r'\s*(->|\.)\s*', lambda m: m.group(1), expr.strip())

        _process_children(body_node)
        return enhanced

    def _anchor_null_checks_after_assignments(
        self,
        body_node: Node,
        slice_lines: Set[int],
    ) -> Set[int]:
        """
        对切片中每条「含分配函数调用的赋值语句」，强制纳入其在 AST 中
        紧随其后（同级兄弟节点）的 NULL / 错误检查 if 块。

        背景：
            PDG 切片按依赖深度截断，常常选中了 `ptr = malloc(...)` 赋值行，
            却漏掉紧跟其后的 `if (ptr == NULL) { ... }` 错误处理块。
            这类块虽与目标行无直接数据/控制依赖，但对理解「分配成功后
            才能使用指针」的语义不可或缺，LLM 需要看到完整的错误处理路径。

        算法：
            遍历函数体（及所有嵌套复合语句）的直接子节点列表。
            对每个节点 N：
              1. 若 N 是赋值/声明语句（含 malloc 类分配调用），且其行在切片中；
              2. 则检查 N 之后的若干个兄弟节点中第一个 if_statement，
                 判断其条件是否为 `var == NULL` / `var == 0` / `!var` 模式
                 （var 来自步骤1中的赋值左值），若匹配则将该 if 全量纳入切片。

        Args:
            body_node: 复合语句节点（compound_statement）
            slice_lines: 当前相对行号集合

        Returns:
            补全后的相对行号集合
        """
        import re
        enhanced = slice_lines.copy()

        # 提取 LHS 完整成员访问路径，例如:
        #   s->s3.alpn_selected = ...  =>  s->s3.alpn_selected
        #   ptr = malloc(...)          =>  ptr
        # 策略：提取 `=`（非 ==、!=、<=、>=）之前的完整表达式（去掉前导空白）
        _LHS_FULL_RE = re.compile(
            r'((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)\s*=(?![>=])'
        )

        # NULL 检查条件的正则：支持完整成员访问路径（含 -> 和 .）
        # 匹配: `expr == NULL/0/nullptr`, `NULL == expr`, `!expr`, `expr != NULL`
        _EXPR_RE = r'[\w][\w\s\->.]*[\w]|[\w]'  # 宽泛匹配含 -> 和 . 的表达式
        _NULL_CHECK_CONDITION_RE = re.compile(
            r'(?:'
            r'((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)\s*==\s*(?:NULL|0|nullptr)'    # expr == NULL
            r'|(?:NULL|0|nullptr)\s*==\s*((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)'   # NULL == expr
            r'|!\s*((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)'                          # !expr
            r'|((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)\s*!=\s*(?:NULL|0|nullptr)'   # expr != NULL (negated NULL check)
            r')'
        )

        def _normalize_expr(expr: str) -> str:
            """规范化表达式：移除多余空白，统一 -> 和 . 周围的空白"""
            return re.sub(r'\s*(->|\.)\s*', lambda m: m.group(1), expr.strip())

        def _get_assigned_var(node: Node, src_bytes: bytes) -> Optional[str]:
            """从赋值/声明节点提取左值完整路径，同时检查右值含分配调用。
            
            返回规范化后的完整左值路径，如 's->s3.alpn_selected'。
            """
            code_text = src_bytes[node.start_byte:node.end_byte].decode("utf8", errors="replace")
            # 必须含分配调用
            if not self._ALLOC_CALL_RE.search(code_text):
                return None
            # 提取完整左值路径（取最后一个匹配，最靠近 = 的完整表达式）
            matches = list(_LHS_FULL_RE.finditer(code_text))
            if not matches:
                return None
            return _normalize_expr(matches[-1].group(1))

        def _if_checks_null_for(if_node: Node, var: str, src_bytes: bytes) -> bool:
            """判断 if 语句的条件是否是对 var（完整路径）的 NULL / 零检查。
            
            同时支持简单变量名（如 ptr）和结构体成员访问路径（如 s->s3.alpn_selected）。
            匹配时忽略空白差异。
            """
            cond_node = if_node.child_by_field_name("condition")
            if cond_node is None:
                return False
            cond_text = src_bytes[cond_node.start_byte:cond_node.end_byte].decode("utf8", errors="replace")
            # 移除最外层括号（条件节点通常包含括号）
            cond_text = cond_text.strip()
            if cond_text.startswith("(") and cond_text.endswith(")"):
                cond_text = cond_text[1:-1].strip()
            m = _NULL_CHECK_CONDITION_RE.search(cond_text)
            if not m:
                return False
            matched_expr = m.group(1) or m.group(2) or m.group(3) or m.group(4)
            if not matched_expr:
                return False
            # 规范化后比较（忽略 -> 和 . 周围的空白）
            return _normalize_expr(matched_expr) == var

        def _process_children(parent: Node, src_bytes: bytes):
            children = [c for c in parent.children if c.is_named]
            for idx, child in enumerate(children):
                # 节点行必须在切片中（至少有一行）
                if not any(self._node_start(child) <= ln <= self._node_end(child)
                           for ln in enhanced):
                    # 递归进复合语句
                    if child.type == "compound_statement":
                        _process_children(child, src_bytes)
                    continue

                # 尝试提取赋值左值变量
                var = _get_assigned_var(child, src_bytes)
                if var is None:
                    # 不是分配赋值语句，但仍递归进复合语句
                    if child.type == "compound_statement":
                        _process_children(child, src_bytes)
                    continue

                # 向后查找紧随的兄弟节点中的 NULL/错误检查 if
                # 策略：最多扫描 5 个后继兄弟节点，允许跳过最多 2 个非 if 语句
                # （如赋值行、continue 等），匹配到第一个符合条件的 if 即止
                skipped_non_if = 0
                for next_child in children[idx + 1:]:
                    if skipped_non_if > 2:
                        break
                    if next_child.type != "if_statement":
                        skipped_non_if += 1
                        continue
                    if _if_checks_null_for(next_child, var, src_bytes):
                        # 命中：将该 if 全量纳入切片
                        before = len(enhanced)
                        for ln in range(self._node_start(next_child),
                                        self._node_end(next_child) + 1):
                            enhanced.add(ln)
                        added = len(enhanced) - before
                        if added:
                            logging.debug(
                                f"_anchor_null_checks: added {added} lines for "
                                f"NULL-check of '{var}' at rel line "
                                f"{self._node_start(next_child)}"
                            )
                    # 只匹配第一个 if（无论是否命中），防止扫描过多
                    break

                # 递归进复合语句内部
                if child.type == "compound_statement":
                    _process_children(child, src_bytes)

        # 使用 enhance_slice 中设置的 _cur_src_bytes 实例变量
        src_bytes = getattr(self, '_cur_src_bytes', b'')
        if src_bytes:
            _process_children(body_node, src_bytes)

        return enhanced

    def _complete_function_signature(self, function_node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        补全函数签名及函数体首尾括号。
        只要切片包含函数内任意行，就把函数签名（含开括号 {）和闭括号 } 都加进来。
        """
        enhanced = slice_lines.copy()
        
        func_start = self._node_start(function_node)
        body_node = function_node.child_by_field_name("body")
        if not body_node:
            return enhanced

        body_start = self._node_start(body_node)  # { 所在行
        body_end   = self._node_end(body_node)    # } 所在行

        # 只要切片包含函数体内任意行，就补全签名和首尾括号
        if slice_lines:
            signature_lines = set(range(func_start, body_start + 1))
            enhanced.update(signature_lines)
            enhanced.add(body_end)
            logging.debug(f"Completing function signature: lines {func_start}-{body_start}, closing brace: {body_end}")

        return enhanced

    def _is_in_node(self, line: int, node: Node, offset: int = 1) -> bool:
        """检查行号是否在节点范围内（offset 保留兼容，实际不再使用）"""
        return self._node_start(node) <= line <= self._node_end(node)

    def _ast_dive_c(self, root: Node, slice_lines: Set[int], offset: int = 1) -> Set[int]:
        """
        递归遍历 AST，对与切片相交的每个控制流语句进行语法块闭合修复。

        规则：
        - 遍历 root 的具名直接子节点；
        - 若子节点与当前 slice_lines 相交，则调用对应 handler 修复；
        - handler 内部会再次调用 _ast_dive_c 递归处理嵌套结构；
        - compound_statement 直接添加 {}/} 后递归内部。
        """
        enhanced = slice_lines.copy()

        for node in root.children:
            if not node.is_named:
                continue

            if not self._intersects(node, enhanced):
                continue

            ntype = node.type
            if ntype == "if_statement":
                enhanced = self._handle_if_statement(node, enhanced)
            elif ntype in ("for_statement", "do_statement"):
                enhanced = self._handle_for_statement(node, enhanced)
            elif ntype == "while_statement":
                enhanced = self._handle_while_statement(node, enhanced)
            elif ntype == "switch_statement":
                enhanced = self._handle_switch_statement(node, enhanced)
            elif ntype == "compound_statement":
                enhanced.add(self._node_start(node))  # {
                enhanced.add(self._node_end(node))    # }
                enhanced = self._ast_dive_c(node, enhanced)
            elif ntype in ("preproc_ifdef", "preproc_ifndef", "preproc_if",
                           "preproc_elif", "preproc_else", "preproc_def",
                           "preproc_function_def"):
                # 预处理指令块：切片命中其内部时，补全 #ifdef/#ifndef 和 #endif 行
                enhanced = self._handle_preproc_block(node, enhanced)
            # 其余语句（表达式语句、声明等）不需要额外补充

        return enhanced

    def _handle_preproc_block(self, node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        处理预处理指令块（#ifdef/#ifndef/#if ... #endif）的语法完整性。

        规则：
        - 若切片命中了块内的任意行（内容行），补全指令头部（#ifdef/#ifndef/#if 行）
          和尾部（#endif 行），确保预处理指令成对出现。
        - 递归处理块内部的嵌套控制流和预处理指令。

        tree-sitter 对 preproc_ifdef 的节点结构：
            preproc_ifdef [start-end]
                identifier [start]       ← 宏名，同 #ifndef 所在行
                <内容节点 ...>
            末尾 end_point 即 #endif 所在行
        """
        enhanced = slice_lines.copy()

        node_start = self._node_start(node)   # #ifdef/#ifndef 行
        node_end   = self._node_end(node)     # #endif 行

        # 判断内容区（第二行到 #endif 前一行）是否有切片行
        content_start = node_start + 1
        content_end   = node_end - 1

        has_content = any(content_start <= ln <= content_end for ln in enhanced)
        if not has_content:
            return enhanced

        # 补全 #ifdef/#ifndef 和 #endif 行
        enhanced.add(node_start)
        enhanced.add(node_end)

        # 递归处理内部控制流（但不重复处理 preproc 头尾行）
        enhanced = self._ast_dive_c(node, enhanced)

        return enhanced

    def _get_body_compound(self, body: Node) -> Optional[Node]:
        """
        获取控制流体节点对应的 compound_statement。
        - 若 body 本身是 compound_statement，直接返回
        - 若 body 是 else_clause，返回其第一个 compound_statement 子节点
        - 否则返回 None（单语句 body）
        """
        if body is None:
            return None
        if body.type == "compound_statement":
            return body
        if body.type == "else_clause":
            for c in body.named_children:
                if c.type == "compound_statement":
                    return c
        return None

    def _ensure_body(self, body: Node, enhanced: Set[int]) -> Set[int]:
        """
        确保一个 body 节点（compound_statement、else_clause 或单语句）的括号行被包含，
        并递归处理其内部控制流结构。

        特别处理 else_clause：tree-sitter 将 else { ... } 解析为 else_clause 节点，
        其内部 compound_statement 没有 'body' 字段，需要通过命名子节点访问。
        """
        enhanced = enhanced.copy()
        if body is None:
            return enhanced
        enhanced.add(self._node_start(body))
        enhanced.add(self._node_end(body))
        compound = self._get_body_compound(body)
        if compound is not None:
            enhanced.add(self._node_start(compound))
            enhanced.add(self._node_end(compound))
            enhanced = self._ast_dive_c(compound, enhanced)
        return enhanced

    def _add_full_header(self, node: Node, enhanced: Set[int]) -> Set[int]:
        """
        将控制语句的完整"头部"（从语句第一行到 body/consequence 的开括号行）全部加入切片。
        确保跨多行的条件表达式、for 初始化部分等不被截断。
        """
        enhanced = enhanced.copy()
        body = (node.child_by_field_name("body") or
                node.child_by_field_name("consequence"))
        if body:
            for ln in range(self._node_start(node), self._node_start(body) + 1):
                enhanced.add(ln)
        else:
            enhanced.add(self._node_start(node))
        return enhanced

    def _handle_if_statement(self, node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        修复 if 语句的语法完整性：
        - 补全 if (...) { 头部（含跨行条件）
        - consequence 体的 {/} 括号（仅当体内有切片行时）
        - 若存在 else 且 alternative 内有切片行，补全 else 关键字行及其体的括号
        - 递归处理 consequence / alternative 内的嵌套结构
        """
        enhanced = slice_lines.copy()

        consequence = node.child_by_field_name("consequence")
        alternative = node.child_by_field_name("alternative")

        # 无花括号单语句 consequence 类型（continue/break/return/goto）
        # 当 if 头部（条件行）已在切片中时，这类语句是 if 结构语义不可分割的部分，
        # 必须主动补全，否则后续 _ast_trim 会因 consequence 为空而删掉整个 if 语句，
        # 导致 "if (!(desc->props & ...)) continue;" 整行消失。
        _SIMPLE_TERMINATOR_TYPES = {
            "continue_statement", "break_statement",
            "return_statement", "goto_statement",
        }

        # 判断 if 头部（节点起始行到 consequence/body 起始行之间，含同行情况）是否有切片行
        def _header_has_content() -> bool:
            header_start = self._node_start(node)
            if consequence:
                body_start = self._node_start(consequence)
            else:
                body_start = self._node_end(node)
            # 当 if 与 consequence 同行（如 `if (cond) continue;`），body_start == header_start，
            # 此时用 <= body_start 确保该行被判定为"有内容"。
            upper = max(body_start, header_start)
            return any(header_start <= ln <= upper for ln in enhanced)

        # 若 consequence 是无花括号的简单终止语句，且 if 头部行已在切片中，
        # 则主动将 consequence 加入切片，使其 "有内容"。
        if (consequence is not None
                and consequence.type in _SIMPLE_TERMINATOR_TYPES
                and _header_has_content()):
            for ln in range(self._node_start(consequence), self._node_end(consequence) + 1):
                enhanced.add(ln)

        # 判断 consequence / alternative 体内是否有切片行
        def _body_has_content(body_node) -> bool:
            if body_node is None:
                return False
            # else_clause：内部有一个 compound_statement，以该 compound 的内部行判断
            if body_node.type == "else_clause":
                compound = self._get_body_compound(body_node)
                if compound is not None:
                    inner_start = self._node_start(compound) + 1
                    inner_end   = self._node_end(compound) - 1
                    if inner_start > inner_end:
                        return False
                    return any(inner_start <= ln <= inner_end for ln in enhanced)
                # else_clause 直接含单语句（else continue; 等）
                s = self._node_start(body_node) + 1  # 跳过 else 关键字所在行
                e = self._node_end(body_node)
                return any(s <= ln <= e for ln in enhanced)
            if body_node.type == "compound_statement":
                inner_start = self._node_start(body_node) + 1
                inner_end   = self._node_end(body_node) - 1
                return any(inner_start <= ln <= inner_end for ln in enhanced)
            else:
                s = self._node_start(body_node)
                e = self._node_end(body_node)
                return any(s <= ln <= e for ln in enhanced)

        cons_has_content = _body_has_content(consequence)
        alt_has_content  = _body_has_content(alternative)

        if not cons_has_content and not alt_has_content:
            # 整个 if 语句无内容，不做任何增强（留给 _ast_trim 处理）
            return enhanced

        # 有内容时才补全 if 头部：if (...) {
        enhanced = self._add_full_header(node, enhanced)

        # 补全 consequence（then 分支）—— 仅当其内部有内容
        if consequence and cons_has_content:
            enhanced = self._ensure_body(consequence, enhanced)

        # 处理 else 分支（仅当 alternative 内有切片行时）
        if alternative and alt_has_content:
            alt_start = self._node_start(alternative)
            enhanced.add(alt_start)
            if alternative.type == "if_statement":
                # else if 递归处理
                enhanced = self._handle_if_statement(alternative, enhanced)
            else:
                enhanced = self._ensure_body(alternative, enhanced)

        return enhanced

    def _handle_for_statement(self, node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        修复 for / do-while 循环的语法完整性：
        - 补全头部（for (...) { 或 do {）
        - 循环体 {/} 括号
        - do-while 还需补全尾部 while(...); 行
        仅当循环体内有切片行时才添加头部和括号。
        """
        enhanced = slice_lines.copy()
        body = node.child_by_field_name("body")

        # 检查 body 内是否有切片行
        def _body_has_content(body_node) -> bool:
            if body_node is None:
                return False
            if body_node.type == "compound_statement":
                inner_start = self._node_start(body_node) + 1
                inner_end   = self._node_end(body_node) - 1
                return any(inner_start <= ln <= inner_end for ln in enhanced)
            else:
                s = self._node_start(body_node)
                e = self._node_end(body_node)
                return any(s <= ln <= e for ln in enhanced)

        if not _body_has_content(body):
            # 循环体无内容，不做增强（留给 _ast_trim 处理）
            return enhanced

        if node.type == "do_statement":
            # do { ... } while (...);
            enhanced.add(self._node_start(node))   # do
            enhanced.add(self._node_end(node))     # while (...);
            if body:
                enhanced = self._ensure_body(body, enhanced)
        else:
            # for (...) { ... }
            enhanced = self._add_full_header(node, enhanced)
            if body:
                enhanced = self._ensure_body(body, enhanced)

        return enhanced

    def _handle_while_statement(self, node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        修复 while 循环的语法完整性：
        - 补全 while (...) { 头部（含跨行条件）
        - 循环体 {/} 括号
        仅当循环体内有切片行时才添加头部和括号。
        """
        enhanced = slice_lines.copy()
        body = node.child_by_field_name("body")

        def _body_has_content(body_node) -> bool:
            if body_node is None:
                return False
            if body_node.type == "compound_statement":
                inner_start = self._node_start(body_node) + 1
                inner_end   = self._node_end(body_node) - 1
                return any(inner_start <= ln <= inner_end for ln in enhanced)
            else:
                s = self._node_start(body_node)
                e = self._node_end(body_node)
                return any(s <= ln <= e for ln in enhanced)

        if not _body_has_content(body):
            return enhanced

        enhanced = self._add_full_header(node, enhanced)
        if body:
            enhanced = self._ensure_body(body, enhanced)
        return enhanced

    def _handle_switch_statement(self, node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        修复 switch 语句的语法完整性：
        - 补全 switch (...) { 头部
        - switch body 的 {/} 括号
        - 对切片相交的 case/default 标签：补全该标签行及其后的语句直到下一个 case/break/}
        """
        enhanced = slice_lines.copy()

        # 补全 switch (...) { 头部
        enhanced = self._add_full_header(node, enhanced)

        body = node.child_by_field_name("body")
        if not body:
            return enhanced

        enhanced.add(self._node_start(body))  # {
        enhanced.add(self._node_end(body))    # }

        # 遍历 case / default 子节点
        case_nodes = [c for c in body.children
                      if c.is_named and c.type in ("case_statement", "default_statement")]

        for case_node in case_nodes:
            if not self._intersects(case_node, enhanced):
                continue

            # 添加 case xxx: / default: 标签行
            enhanced.add(self._node_start(case_node))

            # 递归处理 case 内的控制流
            enhanced = self._ast_dive_c(case_node, enhanced)

            # 补全 case 内的 break/return/continue/goto（由 _ast_add 负责，此处不重复）

        return enhanced

    def _ast_add(self, root: Node, slice_lines: Set[int], offset: int = 1) -> Set[int]:
        """
        补全控制流终止语句：
        - 若切片包含某个 switch case 的内容，但不包含其 break/return/continue/goto，则补全。
        - 若切片包含某个循环体的内容，但对应 continue/break 缺失，则补全。
        这里采用保守策略：只对直接被切片相交的语句块末尾做补全。
        """
        enhanced = slice_lines.copy()

        def _walk(node: Node):
            nonlocal enhanced
            if not node.is_named:
                return
            if not self._intersects(node, enhanced):
                return

            ntype = node.type

            # switch case：补全终止语句
            if ntype == "case_statement":
                enhanced = self._complete_case_terminator(node, enhanced)
            # 循环体：补全可能的 break/continue
            elif ntype in ("for_statement", "while_statement", "do_statement"):
                body = node.child_by_field_name("body")
                if body and self._intersects(body, enhanced):
                    enhanced = self._complete_loop_terminator(body, enhanced)

            for child in node.children:
                _walk(child)

        for child in root.children:
            _walk(child)

        return enhanced

    def _complete_case_terminator(self, case_node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        若 case 语句块内有内容被切片选中，确保 break/return/continue/goto 等终止语句被加入。
        """
        enhanced = slice_lines.copy()
        TERMINATOR_TYPES = {"break_statement", "return_statement",
                            "continue_statement", "goto_statement"}

        for child in case_node.children:
            if not child.is_named:
                continue
            if child.type in TERMINATOR_TYPES:
                # 只要 case 中有任意行被选中，就补全终止语句
                if self._intersects(case_node, enhanced):
                    for ln in range(self._node_start(child), self._node_end(child) + 1):
                        enhanced.add(ln)
        return enhanced

    def _complete_loop_terminator(self, body_node: Node, slice_lines: Set[int]) -> Set[int]:
        """
        若循环体中有内容被切片选中，补全其直接子级 break/continue 语句。
        （不深入嵌套，避免误添加内层循环的 break）
        """
        enhanced = slice_lines.copy()
        TERMINATOR_TYPES = {"break_statement", "continue_statement"}
        for child in body_node.children:
            if not child.is_named:
                continue
            if child.type in TERMINATOR_TYPES:
                for ln in range(self._node_start(child), self._node_end(child) + 1):
                    enhanced.add(ln)
        return enhanced

    def _ast_trim(self, root: Node, slice_lines: Set[int], offset: int = 1) -> Set[int]:
        """
        修剪无效的空语法块：
        - 若 if 语句的 consequence 体内没有任何切片行（仅有 {/}），则移除该 if 语句头部和空体。
        - 若 else 体内没有切片行，移除 else 部分。
        - 若 for/while/do 循环体内没有切片行，移除整个循环语句。
        这里采用保守策略：只移除完全空的结构，避免错误删除。
        """
        enhanced = slice_lines.copy()

        def _is_body_empty(body_node: Node, lines: Set[int]) -> bool:
            """判断一个 body 节点内部是否没有切片行。
            对 compound_statement：检查 {/} 内部区间；
            对 else_clause：检查其内部 compound_statement 的内部区间；
            对单语句 body：直接检查该节点整体是否有行在切片中。
            """
            if body_node is None:
                return True
            if body_node.type == "else_clause":
                compound = self._get_body_compound(body_node)
                if compound is not None:
                    inner_start = self._node_start(compound) + 1
                    inner_end   = self._node_end(compound) - 1
                    if inner_start > inner_end:
                        return True
                    return not any(inner_start <= ln <= inner_end for ln in lines)
                # else 后接单语句（else continue; 等）
                start = self._node_start(body_node) + 1
                end   = self._node_end(body_node)
                return not any(start <= ln <= end for ln in lines)
            if body_node.type == "compound_statement":
                inner_start = self._node_start(body_node) + 1
                inner_end   = self._node_end(body_node) - 1
                if inner_start > inner_end:
                    return True
                return not any(inner_start <= ln <= inner_end for ln in lines)
            else:
                # 单语句 body（无 {}）
                start = self._node_start(body_node)
                end   = self._node_end(body_node)
                return not any(start <= ln <= end for ln in lines)

        def _discard_node(node: Node):
            """移除节点覆盖的所有行"""
            for ln in range(self._node_start(node), self._node_end(node) + 1):
                enhanced.discard(ln)

        def _walk_trim(node: Node):
            nonlocal enhanced
            if not node.is_named:
                return

            if node.type == "if_statement":
                consequence = node.child_by_field_name("consequence")
                alternative = node.child_by_field_name("alternative")

                cons_empty = _is_body_empty(consequence, enhanced)
                alt_empty  = _is_body_empty(alternative, enhanced) if alternative else True

                if cons_empty and alt_empty:
                    # 整个 if 语句没有内容，移除该 if 的所有行（含头部和所有 {/}）
                    _discard_node(node)
                    return  # 不再递归子节点（已全部移除）
                elif cons_empty and not alt_empty:
                    # consequence 为空但 else 有内容：移除 consequence 体 + if 头部
                    if consequence:
                        _discard_node(consequence)
                    # if 头部（从 node 起到 alternative 之前）也移除
                    if alternative:
                        for ln in range(self._node_start(node), self._node_start(alternative)):
                            enhanced.discard(ln)
                    # 递归处理 alternative 内部
                    _walk_trim(alternative)
                    return
                elif not cons_empty and alt_empty and alternative:
                    # else 体为空：移除 else 部分（alternative 节点所有行）
                    _discard_node(alternative)

            elif node.type in ("for_statement", "while_statement", "do_statement"):
                body = node.child_by_field_name("body")
                if _is_body_empty(body, enhanced):
                    # 循环体为空，移除整个循环语句
                    _discard_node(node)
                    return

            for child in node.children:
                _walk_trim(child)

        for child in root.children:
            _walk_trim(child)

        return enhanced


def enhance_slice_with_ast(source_code: str, 
                          slice_lines: Set[int],
                          language: str = "c",
                          function_start_line: int = 1,
                          target_line: Optional[int] = None) -> Set[int]:
    """
    使用 AST 增强切片的便捷函数
    
    Args:
        source_code: 完整源代码（可以是单函数或多函数文件）
        slice_lines: 切片行号集合
        language: 编程语言
        function_start_line: source_code 在原始文件中的起始行号
        target_line: 警告行绝对行号（可选，传入后有助于多函数场景的日志追踪）
    
    Returns:
        增强后的行号集合
    """
    if not TREE_SITTER_AVAILABLE:
        logging.warning("tree-sitter not available, returning original slice")
        return slice_lines
    
    try:
        enhancer = ASTEnhancer(language)
        return enhancer.enhance_slice(source_code, slice_lines, function_start_line, target_line)
    except Exception as e:
        logging.error(f"AST enhancement failed: {e}")
        return slice_lines

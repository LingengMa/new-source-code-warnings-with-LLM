"""
切片引擎核心逻辑
实现基于 PDG 的前向和后向切片算法
"""
import logging
import re
from collections import deque
from typing import Set, List, Tuple, Dict, Optional
from pdg_loader import PDG, PDGNode
import config


class SliceEngine:
    """程序切片引擎"""
    
    def __init__(self, pdg: PDG):
        self.pdg = pdg
        self.visited_nodes: Set[int] = set()

    def backward_slice(self, 
                      criteria_nodes: List[PDGNode], 
                      criteria_identifier: Dict[int, Set[str]] = None,
                      depth: int = config.BACKWARD_DEPTH) -> Set[PDGNode]:
        """
        后向切片：从切片准则向上追溯依赖
        
        Args:
            criteria_nodes: 切片准则节点列表
            criteria_identifier: 行号 -> 标识符集合的映射（用于精确切片）
            depth: 切片深度
            
        Returns:
            切片节点集合
        """
        if criteria_identifier is None:
            criteria_identifier = {}
        
        result_nodes: Set[PDGNode] = set()
        queue = deque([(node, 0) for node in criteria_nodes])
        visited_ids = {node.node_id for node in criteria_nodes}
        
        while queue:
            node, current_depth = queue.popleft()
            
            result_nodes.add(node)
            
            # 达到深度限制
            if current_depth >= depth:
                continue
            
            # 获取前驱节点（DDG 和 CDG）
            preds = self.pdg.get_predecessors(node.node_id, config.DDG_LABEL)
            preds.extend(self.pdg.get_predecessors(node.node_id, config.CDG_LABEL))
            
            for pred_node, edge_label in preds:
                if pred_node.node_id in visited_ids:
                    continue
                
                # 如果指定了标识符过滤
                if node.line_number in criteria_identifier:
                    edge_var = edge_label.replace(config.DDG_LABEL + ': ', '').replace(config.CDG_LABEL + ': ', '')
                    if edge_var and edge_var not in criteria_identifier[node.line_number]:
                        continue
                
                visited_ids.add(pred_node.node_id)
                queue.append((pred_node, current_depth + 1))
        
        return result_nodes
    
    def forward_slice(self,
                     criteria_nodes: List[PDGNode],
                     criteria_identifier: Dict[int, Set[str]] = None,
                     depth: int = config.FORWARD_DEPTH) -> Set[PDGNode]:
        """
        前向切片：从切片准则向下追踪影响
        
        Args:
            criteria_nodes: 切片准则节点列表
            criteria_identifier: 行号 -> 标识符集合的映射
            depth: 切片深度
            
        Returns:
            切片节点集合
        """
        if criteria_identifier is None:
            criteria_identifier = {}
        
        result_nodes: Set[PDGNode] = set()
        queue = deque([(node, 0) for node in criteria_nodes])
        visited_ids = {node.node_id for node in criteria_nodes}
        
        while queue:
            node, current_depth = queue.popleft()
            
            result_nodes.add(node)
            
            # 达到深度限制
            if current_depth >= depth:
                continue
            
            # 获取后继节点（DDG 和 CDG）
            succs = self.pdg.get_successors(node.node_id, config.DDG_LABEL)
            succs.extend(self.pdg.get_successors(node.node_id, config.CDG_LABEL))
            
            for succ_node, edge_label in succs:
                if succ_node.node_id in visited_ids:
                    continue
                
                # 如果指定了标识符过滤
                if node.line_number in criteria_identifier:
                    edge_var = edge_label.replace(config.DDG_LABEL + ': ', '').replace(config.CDG_LABEL + ': ', '')
                    if edge_var and edge_var not in criteria_identifier[node.line_number]:
                        continue
                
                visited_ids.add(succ_node.node_id)
                queue.append((succ_node, current_depth + 1))
        
        return result_nodes
    
    def slice(self, 
             target_line: int,
             criteria_identifier: Dict[int, Set[str]] = None,
             backward_depth: int = config.BACKWARD_DEPTH,
             forward_depth: int = config.FORWARD_DEPTH,
             rule_id: str = None) -> Tuple[Set[PDGNode], Dict]:
        """
        执行完整的双向切片，返回节点集合
        
        Args:
            target_line: 目标行号
            criteria_identifier: 标识符过滤字典
            backward_depth: 后向切片深度
            forward_depth: 前向切片深度
            rule_id: 告警规则 ID，用于按规则覆盖切片深度和策略
            
        Returns:
            (切片节点集合, 元数据字典)
        """
        # 按 rule_id 覆盖切片深度
        if rule_id:
            override = config.RULE_SLICE_DEPTH_OVERRIDES.get(rule_id)
            if override:
                backward_depth = override.get("backward", backward_depth)
                forward_depth  = override.get("forward",  forward_depth)
                logging.info(f"rule_id={rule_id!r}: depth overridden to backward={backward_depth}, forward={forward_depth}")

        # 查找目标行的节点
        criteria_nodes = self.pdg.get_nodes_by_line(target_line)
        if not criteria_nodes:
            # 当精确行号找不到节点时（如 Joern 对宏展开行的行号偏移），
            # 尝试在 ±3 行范围内寻找最近节点作为切片准则
            logging.warning(f"No nodes found for line {target_line}, trying nearby lines ±3")
            for offset in range(1, 4):
                for candidate_line in [target_line - offset, target_line + offset]:
                    criteria_nodes = self.pdg.get_nodes_by_line(candidate_line)
                    if criteria_nodes:
                        logging.info(f"Found {len(criteria_nodes)} nodes at nearby line {candidate_line} (offset {offset:+d})")
                        break
                if criteria_nodes:
                    break
        if not criteria_nodes:
            logging.warning(f"No nodes found for line {target_line}")
            return set(), {}
        
        logging.info(f"Found {len(criteria_nodes)} nodes for line {target_line}")

        # 按规则分派专用切片策略
        UNBOUNDED_WRITE_RULES = {
            "cpp/unbounded-write",
            "cpp/overflow-buffer",
        }
        NULL_CHECK_RULES = {
            "cpp/inconsistent-null-check",
            "cpp/nullptr-dereference",
        }

        if rule_id and rule_id in UNBOUNDED_WRITE_RULES:
            # ----------------------------------------------------------------
            # 缓冲区越界写专用策略（cpp/unbounded-write 等）
            # ----------------------------------------------------------------
            backward_nodes = self.backward_slice(
                criteria_nodes, criteria_identifier, backward_depth
            )
            forward_nodes = self.forward_slice(
                criteria_nodes, criteria_identifier, forward_depth
            )
            all_slice_nodes = backward_nodes.union(forward_nodes)

            # 收集警告行所有标识符 + 后向切片中含 size/len 关键词的变量
            scan_vars: Set[str] = set()
            for node in criteria_nodes:
                scan_vars.update(self._extract_identifiers(node.code))
            _SIZE_KW = re.compile(r'\b(size|len|length|n|sz|count|num|max|limit)\b')
            for node in backward_nodes:
                if node.code and _SIZE_KW.search(node.code):
                    scan_vars.update(self._extract_identifiers(node.code))
            logging.info(f"unbounded-write rule: scan_vars={scan_vars}")

            if scan_vars:
                extra = self._text_scan_var_uses(scan_vars, {n.node_id for n in all_slice_nodes})
                if extra:
                    logging.info(f"unbounded-write rule: text scan补全 {len(extra)} 个节点")
                    all_slice_nodes = all_slice_nodes.union(extra)

            logging.info(f"unbounded-write strategy: backward={len(backward_nodes)}, forward={len(forward_nodes)}, total={len(all_slice_nodes)}")

        elif rule_id and rule_id == "cpp/use-after-free":
            # ----------------------------------------------------------------
            # use-after-free 专用策略
            #
            # 目标：对 LLM 提供完整的内存生命周期上下文，包括：
            #   (a) alloc 行 + 其紧跟的 NULL 检查（已由 ast_enhancer 处理）
            #   (b) 警告行（use 点）及其数据依赖的上下文
            #   (c) 同一指针（含结构体成员路径）的所有 free / alloc / 赋值操作
            #
            # 关键改进：
            #   1. 提取警告行及后向切片中赋值语句的【完整左值路径】
            #      （如 s->s3.alpn_selected），而非仅简单变量名
            #   2. 对每条成员路径，用文本扫描找到函数内所有引用该路径的节点
            #      （free / 再赋值 / 条件检查等）
            #   3. 对路径末尾的简单名（如 alpn_selected）也做宽泛扫描，
            #      捕获不同前缀对象的同名成员操作
            # ----------------------------------------------------------------
            backward_nodes = self.backward_slice(
                criteria_nodes, criteria_identifier, backward_depth
            )
            forward_nodes = self.forward_slice(
                criteria_nodes, criteria_identifier, forward_depth
            )
            all_slice_nodes = backward_nodes.union(forward_nodes)

            # 1. 从警告行 + 后向切片节点提取完整左值路径
            lhs_full_paths = self._extract_lhs_full_paths(criteria_nodes)
            # 同时从后向切片节点补充（可能存在 ptr = alloc 在后向切片里）
            lhs_full_paths.update(self._extract_lhs_full_paths(list(backward_nodes)))
            logging.info(f"use-after-free rule: lhs_full_paths={lhs_full_paths}")

            if lhs_full_paths:
                extra = self._text_scan_member_uses(
                    lhs_full_paths, {n.node_id for n in all_slice_nodes}
                )
                if extra:
                    logging.info(f"use-after-free rule: member scan补全 {len(extra)} 个节点")
                    all_slice_nodes = all_slice_nodes.union(extra)

            logging.info(f"use-after-free strategy: backward={len(backward_nodes)}, forward={len(forward_nodes)}, total={len(all_slice_nodes)}")

        elif rule_id and rule_id in NULL_CHECK_RULES:
            # ----------------------------------------------------------------
            # 返回值空值检查遗漏专用策略（cpp/inconsistent-null-check 等）
            #
            # 策略：
            #   a. 提取警告行赋值左值变量（如 desc）
            #   b. 浅后向切片获取 for/if 等控制流上下文
            #   c. 前向切片（无标识符过滤）追踪变量后续使用
            #   d. 文本扫描强制补全 lhs_vars 相关的所有使用节点
            # ----------------------------------------------------------------
            lhs_vars = self._extract_lhs_vars(criteria_nodes)
            logging.info(f"null-check rule: lhs_vars={lhs_vars}")

            backward_nodes = self.backward_slice(
                criteria_nodes,
                criteria_identifier=criteria_identifier,
                depth=backward_depth,
            )
            forward_nodes = self.forward_slice(
                criteria_nodes,
                criteria_identifier=None,
                depth=forward_depth,
            )
            all_slice_nodes = backward_nodes.union(forward_nodes)

            if lhs_vars:
                extra = self._text_scan_var_uses(lhs_vars, {n.node_id for n in all_slice_nodes})
                if extra:
                    logging.info(f"null-check rule: text scan补全 {len(extra)} 个 lhs_vars 使用节点")
                    all_slice_nodes = all_slice_nodes.union(extra)

            logging.info(f"null-check strategy: backward={len(backward_nodes)}, forward={len(forward_nodes)}, total={len(all_slice_nodes)}")

        else:
            # ----------------------------------------------------------------
            # 通用双向切片
            # ----------------------------------------------------------------
            backward_nodes = self.backward_slice(
                criteria_nodes, criteria_identifier, backward_depth
            )
            forward_nodes = self.forward_slice(
                criteria_nodes, criteria_identifier, forward_depth
            )
            all_slice_nodes = backward_nodes.union(forward_nodes)

            if config.ENABLE_DEF_USE_AUGMENTATION:
                aug_nodes = self._def_use_augment(criteria_nodes, all_slice_nodes, forward_depth)
                if aug_nodes:
                    logging.info(f"def-use augmentation added {len(aug_nodes)} extra nodes")
                    all_slice_nodes = all_slice_nodes.union(aug_nodes)

        # 提取行号用于元数据统计
        slice_lines = {node.line_number for node in all_slice_nodes if node.line_number}

        # 元数据
        metadata = {
            "function_name": self.pdg.method_name,
            "function_start_line": self.pdg.start_line,
            "function_end_line": self.pdg.end_line,
            "target_line": target_line,
            "backward_nodes": len(backward_nodes),
            "forward_nodes": len(forward_nodes) - len(criteria_nodes), # 减去重复的准则节点
            "total_slice_nodes": len(all_slice_nodes),
            "total_slice_lines": len(slice_lines),
            "slice_density": len(slice_lines) / (self.pdg.end_line - self.pdg.start_line + 1) if self.pdg.end_line and self.pdg.start_line else 0
        }
        
        logging.info(f"Slice complete: {len(all_slice_nodes)} nodes found.")
        
        return all_slice_nodes, metadata

    # ------------------------------------------------------------------
    # 返回值变量使用增强
    # ------------------------------------------------------------------

    # --------------------------------------------------------------------------
    # 左值提取正则：两套策略
    # --------------------------------------------------------------------------

    # 策略 A：提取简单变量名（用于 null-check / def-use 场景，不含成员路径）
    #   fd = expr               => fd
    #   Type *fd = expr         => fd
    # 不匹配结构体成员赋值 (s->field = ...)
    _LHS_SIMPLE_RE = re.compile(
        r'(?<![>\.])'
        r'\b([A-Za-z_][A-Za-z0-9_]*)'
        r'\s*=(?![=>])'
    )

    # 策略 B：提取完整左值路径，包括结构体成员访问（用于 use-after-free 追踪）
    #   s->s3.alpn_selected = expr   => s->s3.alpn_selected
    #   ptr = malloc(...)            => ptr
    _LHS_FULL_RE = re.compile(
        r'((?:\w+(?:\s*->\s*|\s*\.\s*))*\w+)\s*=(?![>=])'
    )

    # 用于保留兼容的别名（已有代码使用 _LHS_RE）
    _LHS_RE = _LHS_SIMPLE_RE

    @staticmethod
    def _normalize_member_expr(expr: str) -> str:
        """规范化成员访问表达式，去除 -> 和 . 周围的多余空白"""
        return re.sub(r'\s*(->|\.)\s*', lambda m: m.group(1), expr.strip())

    def _extract_lhs_vars(self, nodes: List[PDGNode]) -> Set[str]:
        """
        从节点代码中提取被赋值的简单左值变量名（不含路径）。
        用于 null-check / def-use augmentation 场景。
        """
        vars_: Set[str] = set()
        for node in nodes:
            code = node.code.strip()
            if not code or '=' not in code:
                continue
            stripped = code.lstrip()
            if stripped.startswith(('if', 'while', 'for', 'return', 'assert')):
                continue
            matches = list(self._LHS_SIMPLE_RE.finditer(code))
            if matches:
                vars_.add(matches[-1].group(1))
        return vars_

    def _extract_lhs_full_paths(self, nodes: List[PDGNode]) -> Set[str]:
        """
        从节点代码中提取被赋值的完整左值路径（含结构体成员访问）。
        例如：
            s->s3.alpn_selected = OPENSSL_malloc(len)
            => 'S->s3.alpn_selected'（规范化后）
        用于 use-after-free 场景，追踪成员变量的定义与使用。
        返回规范化后的路径集合，以及每条路径末尾的简单变量名（用于宽泛匹配）。
        """
        full_paths: Set[str] = set()
        for node in nodes:
            code = node.code.strip()
            if not code or '=' not in code:
                continue
            stripped = code.lstrip()
            if stripped.startswith(('if', 'while', 'for', 'return', 'assert')):
                continue
            matches = list(self._LHS_FULL_RE.finditer(code))
            if matches:
                path = self._normalize_member_expr(matches[-1].group(1))
                full_paths.add(path)
                # 同时加入路径末尾的简单名（如 alpn_selected），用于宽泛扫描
                leaf = path.split('->')[-1].split('.')[-1].strip()
                if leaf and leaf != path:
                    full_paths.add(leaf)
        return full_paths

    def _def_use_augment(self,
                         criteria_nodes: List[PDGNode],
                         existing_nodes: Set[PDGNode],
                         forward_depth: int) -> Set[PDGNode]:
        """
        对警告行产生的赋值变量，在 PDG 中搜索其所有后续使用节点（DDG 出边），
        将这些使用节点加入切片，并以它们为新准则再做一轮前向切片。

        Args:
            criteria_nodes: 警告行的原始节点列表
            existing_nodes: 当前已有的切片节点集合
            forward_depth: 前向切片深度

        Returns:
            新增的节点集合（不含已有节点）
        """
        # 1. 提取警告行赋值的左值变量
        lhs_vars = self._extract_lhs_vars(criteria_nodes)
        if not lhs_vars:
            return set()

        logging.info(f"def-use augmentation: tracking variables {lhs_vars}")

        existing_ids = {n.node_id for n in existing_nodes}
        extra_nodes: Set[PDGNode] = set()

        # 2. 遍历 PDG 中所有 DDG 出边，找出以这些变量为标签的边的目标节点
        for criteria_node in criteria_nodes:
            succs = self.pdg.get_successors(criteria_node.node_id, config.DDG_LABEL)
            for succ_node, edge_label in succs:
                # DDG 边标签形如 "DDG: fd"，提取变量名
                edge_var = edge_label.replace(config.DDG_LABEL + ': ', '').strip()
                if edge_var not in lhs_vars:
                    continue
                if succ_node.node_id in existing_ids:
                    continue
                extra_nodes.add(succ_node)

        # 3. 若 DDG 直接出边没找到（Joern 有时对指针解引用的边标注缺失），
        #    则扫描整个函数所有节点，找代码中包含这些变量的节点作为补充
        if not extra_nodes:
            logging.debug("DDG direct edges not found for lhs vars, falling back to text scan")
            extra_nodes = self._text_scan_var_uses(lhs_vars, existing_ids)

        if not extra_nodes:
            return set()

        # 4. 以这些新增使用节点为准则，再做一轮前向切片（深度减半，避免过度膨胀）
        augmented_forward = self.forward_slice(
            list(extra_nodes),
            depth=max(1, forward_depth // 2)
        )

        all_extra = extra_nodes.union(augmented_forward)
        # 只返回真正新增的节点
        return {n for n in all_extra if n.node_id not in existing_ids}

    def _text_scan_var_uses(self,
                            lhs_vars: Set[str],
                            existing_ids: Set[int]) -> Set[PDGNode]:
        """
        在 PDG 全图节点的 CODE 属性中，文本扫描含有目标变量名的节点，
        作为 DDG 边缺失时的兜底手段。
        只匹配变量作为独立 token 出现的情况（避免误匹配前缀相同的变量）。
        """
        found: Set[PDGNode] = set()
        patterns = {v: re.compile(r'\b' + re.escape(v) + r'\b') for v in lhs_vars}

        for node_id in self.pdg.g.nodes():
            if node_id in existing_ids:
                continue
            node = PDGNode(node_id, self.pdg.g.nodes[node_id])
            if node.line_number is None:
                continue
            code = node.code.strip()
            if not code:
                continue
            for var, pat in patterns.items():
                if pat.search(code):
                    found.add(node)
                    logging.debug(f"text scan found use of '{var}' at line {node.line_number}: {code[:60]}")
                    break

        return found

    def _text_scan_member_uses(self,
                               member_paths: Set[str],
                               existing_ids: Set[int]) -> Set[PDGNode]:
        """
        在 PDG 全图节点代码中扫描「成员路径」的所有使用节点。
        
        与 _text_scan_var_uses 的区别：
          - 支持结构体成员路径（如 `s->s3.alpn_selected`）的精确匹配
          - 同时对路径末尾的简单名做宽泛词边界匹配（如 `alpn_selected`）
          - 特别关注 free/释放操作（OPENSSL_free / free 等）
        
        参数：
            member_paths: 规范化后的成员路径集合（如 {'s->s3.alpn_selected', 'alpn_selected'}）
            existing_ids: 已在切片中的节点 id 集合
        
        返回：
            新增的节点集合
        """
        found: Set[PDGNode] = set()
        
        # 释放函数模式（与 _ALLOC_CALL_RE 对应的释放侧）
        _FREE_RE = re.compile(
            r'\b(OPENSSL_free|CRYPTO_free|free|g_free|PyMem_Free|zfree)\s*\('
        )

        # 为每条路径编译两种模式：
        #   1. 完整路径精确匹配（对含 -> / . 的路径）
        #   2. 末尾简单名的词边界匹配（宽泛）
        path_patterns: List[tuple] = []
        for path in member_paths:
            # 完整路径：将 -> 和 . 的转义序列改为允许空白的模式
            # re.escape 会将 -> 变成 \-\>，需要替换为 \s*->\s*
            escaped = re.escape(path)
            # 替换 \-\> 为 \s*->\s*，替换 \. 为 \s*\.\s*
            escaped = escaped.replace(r'\-\>', r'\s*->\s*').replace(r'\.', r'\s*\.\s*')
            full_pat = re.compile(escaped)
            # 末尾简单名
            leaf = path.split('->')[-1].split('.')[-1].strip()
            leaf_pat = re.compile(r'\b' + re.escape(leaf) + r'\b') if leaf else None
            path_patterns.append((path, full_pat, leaf_pat))

        for node_id in self.pdg.g.nodes():
            if node_id in existing_ids:
                continue
            node = PDGNode(node_id, self.pdg.g.nodes[node_id])
            if node.line_number is None:
                continue
            code = node.code.strip()
            if not code:
                continue

            matched = False
            for path, full_pat, leaf_pat in path_patterns:
                # 优先用完整路径精确匹配
                if '->' in path or '.' in path:
                    if full_pat.search(code):
                        matched = True
                        logging.debug(
                            f"member scan (full path '{path}') at line {node.line_number}: {code[:70]}"
                        )
                        break
                # 对简单名，只在含 free 操作或赋值操作时才宽泛匹配，避免误引入无关节点
                if leaf_pat and leaf_pat.search(code):
                    # 含 free 操作、赋值操作或 NULL 检查时才纳入
                    if (_FREE_RE.search(code)
                            or re.search(r'=(?![>=])', code)
                            or re.search(r'==\s*NULL|!=\s*NULL|==\s*0\b', code)):
                        matched = True
                        logging.debug(
                            f"member scan (leaf '{path}') at line {node.line_number}: {code[:70]}"
                        )
                        break

            if matched:
                found.add(node)

        return found

    # 提取代码片段中所有 C 标识符（变量名、函数名）
    _IDENT_RE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)\b')
    _C_KEYWORDS = {
        'if', 'else', 'while', 'for', 'do', 'switch', 'case', 'default',
        'break', 'continue', 'return', 'goto', 'sizeof', 'typeof',
        'int', 'char', 'long', 'short', 'unsigned', 'signed', 'float',
        'double', 'void', 'struct', 'union', 'enum', 'typedef', 'static',
        'const', 'extern', 'inline', 'volatile', 'register', 'auto',
        'NULL', 'nullptr', 'true', 'false',
    }

    def _extract_identifiers(self, code: str) -> Set[str]:
        if not code:
            return set()
        idents = set(self._IDENT_RE.findall(code))
        return {v for v in idents if v not in self._C_KEYWORDS and len(v) > 1}

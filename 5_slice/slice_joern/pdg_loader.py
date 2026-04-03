"""
PDG 加载和解析模块
负责从 Joern 生成的 DOT 文件中加载和解析程序依赖图
"""
import os
import networkx as nx
from typing import Dict, List, Optional, Tuple, Set
import logging


class PDGNode:
    """PDG 节点类"""
    
    def __init__(self, node_id: int, attrs: dict):
        self.node_id = node_id
        self.attrs = attrs
        
    @property
    def line_number(self) -> Optional[int]:
        """获取行号"""
        if 'LINE_NUMBER' in self.attrs:
            return int(self.attrs['LINE_NUMBER'])
        return None
    
    @property
    def node_type(self) -> str:
        """获取节点类型"""
        return self.attrs.get('NODE_TYPE', 'UNKNOWN')
    
    @property
    def code(self) -> str:
        """获取代码文本"""
        code = self.attrs.get('CODE', '')
        # 反转义
        code = code.replace(r'__quote__', '"')
        code = code.replace(r'__Backslash__', '\\')
        code = code.replace(r'\n', '\n')
        return code
    
    @property
    def filename(self) -> Optional[str]:
        """获取文件名"""
        return self.attrs.get('FILENAME')
    
    def __repr__(self):
        return f"PDGNode({self.node_id}, line={self.line_number}, type={self.node_type})"


class PDG:
    """程序依赖图类"""
    
    def __init__(self, pdg_path: str):
        self.pdg_path = pdg_path
        if not os.path.exists(pdg_path):
            raise FileNotFoundError(f"PDG file not found: {pdg_path}")
        
        # 加载图
        self.g: nx.MultiDiGraph = nx.nx_agraph.read_dot(pdg_path)
        
        # 查找 METHOD 节点
        self._method_node = None
        for node in self.g.nodes():
            if self.g.nodes[node].get('NODE_TYPE') == 'METHOD':
                self._method_node = node
                break
        
        if self._method_node is None:
            raise ValueError(f"No METHOD node found in {pdg_path}")
    
    @property
    def method_node(self) -> PDGNode:
        """获取方法节点"""
        return PDGNode(self._method_node, self.g.nodes[self._method_node])
    
    @property
    def method_name(self) -> Optional[str]:
        """获取方法名"""
        return self.g.nodes[self._method_node].get('NAME')
    
    @property
    def start_line(self) -> Optional[int]:
        """获取方法起始行"""
        line = self.g.nodes[self._method_node].get('LINE_NUMBER')
        return int(line) if line else None
    
    @property
    def end_line(self) -> Optional[int]:
        """获取方法结束行"""
        line = self.g.nodes[self._method_node].get('LINE_NUMBER_END')
        return int(line) if line else None
    
    @property
    def filename(self) -> Optional[str]:
        """获取文件名"""
        return self.g.nodes[self._method_node].get('FILENAME')
    
    def get_node(self, node_id) -> PDGNode:
        """获取指定节点"""
        if isinstance(node_id, PDGNode):
            node_id = node_id.node_id
        return PDGNode(node_id, self.g.nodes[node_id])
    
    def get_ast_parent(self, node_id: int) -> Optional[PDGNode]:
        """获取节点的 AST 父节点"""
        # 在 Joern 的 PDG 导出中，AST 边通常没有特定标签
        # 我们需要找到指向该节点的、没有标签或标签为 'AST' 的边
        for pred_id in self.g.predecessors(node_id):
            # NetworkX 中，多重图的边是 (u, v, key)
            # key 通常是边的标签
            for key, data in self.g[pred_id][node_id].items():
                label = data.get('label', '')
                # Joern 的 AST 边通常是 'AST'
                if 'AST' in label:
                    return self.get_node(pred_id)
        return None

    def get_ast_children(self, node_id: int) -> List[PDGNode]:
        """获取节点的 AST 子节点"""
        children = []
        for succ_id in self.g.successors(node_id):
            for key, data in self.g[node_id][succ_id].items():
                label = data.get('label', '')
                if 'AST' in label:
                    # 按子节点顺序排序
                    order = data.get('order', -1)
                    children.append((self.get_node(succ_id), int(order)))
        
        # 根据 order 属性排序
        return [node for node, order in sorted(children, key=lambda x: x[1])]

    def get_nodes_by_line(self, line_number: int) -> List[PDGNode]:
        """根据行号获取节点列表"""
        nodes = []
        for node_id in self.g.nodes():
            node = PDGNode(node_id, self.g.nodes[node_id])
            if node.line_number == line_number:
                nodes.append(node)
        return nodes
    
    def get_predecessors(self, node_id, label: Optional[str] = None) -> List[Tuple[PDGNode, str]]:
        """获取前驱节点"""
        preds = []
        for pred_id in self.g.predecessors(node_id):
            for key, edge_data in self.g[pred_id][node_id].items():
                edge_label = edge_data.get('label', '')
                if label is None or edge_label.startswith(label):
                    preds.append((PDGNode(pred_id, self.g.nodes[pred_id]), edge_label))
        return preds
    
    def get_successors(self, node_id, label: Optional[str] = None) -> List[Tuple[PDGNode, str]]:
        """获取后继节点"""
        succs = []
        for succ_id in self.g.successors(node_id):
            for key, edge_data in self.g[node_id][succ_id].items():
                edge_label = edge_data.get('label', '')
                if label is None or edge_label.startswith(label):
                    succs.append((PDGNode(succ_id, self.g.nodes[succ_id]), edge_label))
        return succs
    
    def count_nodes_near_line(self, target_line: int, radius: int = 200) -> int:
        """
        统计与目标行距离在 radius 以内的节点数量，
        用于在无法精确匹配行范围时评估 PDG 的相关性。
        """
        count = 0
        for node_id in self.g.nodes():
            node = PDGNode(node_id, self.g.nodes[node_id])
            ln = node.line_number
            if ln is not None and abs(ln - target_line) <= radius:
                count += 1
        return count

    def has_node_at_line(self, target_line: int) -> bool:
        """检查该 PDG 是否存在精确在目标行的节点"""
        for node_id in self.g.nodes():
            node = PDGNode(node_id, self.g.nodes[node_id])
            if node.line_number == target_line:
                return True
        return False
    
    def __repr__(self):
        return f"PDG({self.method_name}, {self.filename}, lines {self.start_line}-{self.end_line})"


class PDGLoader:
    """PDG 加载器"""
    
    def __init__(self, pdg_dir: str):
        self.pdg_dir = pdg_dir
        self.pdgs: Dict[str, List[PDG]] = {}  # filename -> [PDG]
        self._load_all_pdgs()
    
    def _load_all_pdgs(self):
        """加载所有 PDG 文件"""
        logging.info(f"Loading PDGs from {self.pdg_dir}")
        
        # 遍历项目目录
        for project_name in os.listdir(self.pdg_dir):
            project_pdg_dir = os.path.join(self.pdg_dir, project_name)
            if not os.path.isdir(project_pdg_dir):
                continue
            
            # 遍历 PDG 文件
            for pdg_file in os.listdir(project_pdg_dir):
                if not pdg_file.endswith('-pdg.dot'):
                    continue
                
                pdg_path = os.path.join(project_pdg_dir, pdg_file)
                try:
                    pdg = PDG(pdg_path)
                    filename = pdg.filename
                    
                    if filename:
                        if filename not in self.pdgs:
                            self.pdgs[filename] = []
                        self.pdgs[filename].append(pdg)
                except Exception as e:
                    logging.warning(f"Failed to load {pdg_path}: {e}")
        
        logging.info(f"Loaded {sum(len(v) for v in self.pdgs.values())} PDGs from {len(self.pdgs)} files")
    
    def find_pdg_for_line(self, filename: str, line_number: int) -> Optional[PDG]:
        """查找包含指定行的 PDG"""
        if filename not in self.pdgs:
            logging.warning(f"No PDGs found for file: {filename}")
            return None
        
        for pdg in self.pdgs[filename]:
            if pdg.start_line and pdg.end_line:
                if pdg.start_line <= line_number <= pdg.end_line:
                    return pdg
        
        logging.warning(f"No PDG found for {filename}:{line_number}")
        return None
    
    def best_pdg_for_line(self, filename: str, line_number: int) -> Optional[PDG]:
        """
        宽松 PDG 查找方法，
        在无法精确匹配行范围时找到目标行附近节点最多的 PDG。
        """
        if filename not in self.pdgs:
            logging.warning(f"No PDGs found for file: {filename}")
            return None
        
        # 先尝试精确查找
        pdg = self.find_pdg_for_line(filename, line_number)
        if pdg:
            return pdg
        
        # 宽松查找
        max_count = 0
        best_pdg = None
        for pdg in self.pdgs[filename]:
            if pdg.has_node_at_line(line_number):
                return pdg
            
            # 统计与目标行相近的节点数量
            count = pdg.count_nodes_near_line(line_number)
            if count > max_count:
                max_count = count
                best_pdg = pdg
        
        return best_pdg
    
    def get_all_pdgs_for_file(self, filename: str) -> List[PDG]:
        """获取文件的所有 PDG"""
        return self.pdgs.get(filename, [])

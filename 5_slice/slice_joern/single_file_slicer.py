"""
单文件切片分析器
直接对单个 C/C++ 文件进行切片分析，使用 Joern 实时生成 PDG
支持多进程并行处理和断点续传
"""
import os
import json
import logging
import subprocess
import tempfile
import shutil
from typing import Dict, List, Set, Tuple, Optional
import traceback
from multiprocessing import Pool, Manager, Lock
import time

import config
from pdg_loader import PDG, PDGNode
from slice_engine import SliceEngine


def _find_file_in_repo(project_dir: str, file_path: str) -> Optional[str]:
    """
    在项目仓库目录中定位源文件。
    先尝试直接拼接路径，若不存在则递归搜索同名文件（basename 匹配）。
    """
    direct = os.path.join(project_dir, file_path)
    if os.path.exists(direct):
        return direct
    basename = os.path.basename(file_path)
    for root, _, files in os.walk(project_dir):
        if basename in files:
            return os.path.join(root, basename)
    return None


logging.basicConfig(
    level=logging.INFO if config.VERBOSE else logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class SingleFileSlicerException(Exception):
    """单文件切片器异常"""
    pass


class JoernAnalyzer:
    """Joern 分析器 - 对单个文件生成 PDG"""
    
    def __init__(self, joern_path: str = "/opt/joern-cli"):
        self.joern_path = joern_path
        self.joern_parse = os.path.join(joern_path, "joern-parse")
        self.joern_export = os.path.join(joern_path, "joern-export")
        
        # 检查 Joern 是否可用
        if not os.path.exists(self.joern_parse):
            raise SingleFileSlicerException(f"Joern not found at {joern_path}")
    
    def analyze_file(self, source_file: str, output_dir: str) -> str:
        """
        分析单个源文件，生成 PDG
        
        Args:
            source_file: 源文件路径
            output_dir: 输出目录
            
        Returns:
            PDG 目录路径
        """
        logging.info(f"Analyzing file with Joern: {source_file}")
        
        # 创建临时目录结构
        code_dir = os.path.join(output_dir, "code")
        os.makedirs(code_dir, exist_ok=True)
        
        # 复制源文件到临时目录
        file_name = os.path.basename(source_file)
        target_file = os.path.join(code_dir, file_name)
        shutil.copy2(source_file, target_file)
        
        # 生成 CPG
        logging.info("Generating CPG...")
        try:
            subprocess.run(
                [self.joern_parse, '--language', 'c', os.path.abspath(code_dir)],
                cwd=output_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60
            )
        except subprocess.TimeoutExpired:
            raise SingleFileSlicerException("Joern parse timeout")
        except subprocess.CalledProcessError as e:
            raise SingleFileSlicerException(f"Joern parse failed: {e.stderr.decode()}")
        
        # 导出 PDG
        pdg_dir = os.path.join(output_dir, 'pdg')
        logging.info("Exporting PDG...")
        try:
            subprocess.run(
                [self.joern_export, '--repr', 'pdg', '--out', os.path.abspath(pdg_dir)],
                cwd=output_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60
            )
        except subprocess.TimeoutExpired:
            raise SingleFileSlicerException("Joern export timeout")
        except subprocess.CalledProcessError as e:
            raise SingleFileSlicerException(f"Joern export failed: {e.stderr.decode()}")
        
        # 导出 CFG
        cfg_dir = os.path.join(output_dir, 'cfg')
        logging.info("Exporting CFG...")
        try:
            subprocess.run(
                [self.joern_export, '--repr', 'cfg', '--out', os.path.abspath(cfg_dir)],
                cwd=output_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60
            )
        except Exception as e:
            logging.warning(f"CFG export failed (non-critical): {e}")
        
        # 导出完整 CPG
        cpg_dir = os.path.join(output_dir, 'cpg')
        logging.info("Exporting CPG...")
        try:
            subprocess.run(
                [self.joern_export, '--repr', 'all', '--out', os.path.abspath(cpg_dir)],
                cwd=output_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=True,
                timeout=60
            )
        except Exception as e:
            logging.warning(f"CPG export failed (non-critical): {e}")
        
        logging.info(f"✓ Analysis complete. PDG saved to {pdg_dir}")
        return pdg_dir
    
    def preprocess_pdg(self, pdg_dir: str, cfg_dir: str, cpg_dir: str):
        """
        预处理 PDG：合并 CFG，清理无用边
        
        这个函数参考了 Mystique 项目中的 joern.py 的预处理逻辑
        """
        import networkx as nx
        
        logging.info("Preprocessing PDGs...")
        
        if not os.path.exists(cpg_dir) or not os.path.exists(os.path.join(cpg_dir, 'export.dot')):
            logging.warning("CPG not found, skipping preprocessing")
            return
        
        try:
            cpg = nx.nx_agraph.read_dot(os.path.join(cpg_dir, 'export.dot'))
        except Exception as e:
            logging.warning(f"Failed to load CPG: {e}")
            return
        
        for pdg_file in os.listdir(pdg_dir):
            if not pdg_file.endswith('-pdg.dot'):
                continue
            
            file_id = pdg_file.split('-')[0]
            pdg_path = os.path.join(pdg_dir, pdg_file)
            cfg_path = os.path.join(cfg_dir, f'{file_id}-cfg.dot')
            
            try:
                pdg_graph = nx.nx_agraph.read_dot(pdg_path)
                
                # 加载 CFG（如果存在）
                if os.path.exists(cfg_path):
                    cfg_graph = nx.nx_agraph.read_dot(cfg_path)
                    pdg_graph = nx.compose(pdg_graph, cfg_graph)
                
                # 清理空的 DDG 边
                edges_to_remove = []
                for u, v, k, d in pdg_graph.edges(data=True, keys=True):
                    label = d.get('label', '')
                    if label in ['DDG: ', 'DDG: this']:
                        edges_to_remove.append((u, v, k))
                
                pdg_graph.remove_edges_from(edges_to_remove)
                
                # 添加 CFG 标签
                for u, v, k, d in pdg_graph.edges(data=True, keys=True):
                    if 'label' not in d:
                        pdg_graph.edges[u, v, k]['label'] = 'CFG'
                
                # 从 CPG 复制节点属性
                for node in pdg_graph.nodes:
                    if node in cpg.nodes:
                        for key, value in cpg.nodes[node].items():
                            pdg_graph.nodes[node][key] = value
                    
                    # 设置 NODE_TYPE
                    if 'label' in pdg_graph.nodes[node]:
                        pdg_graph.nodes[node]['NODE_TYPE'] = pdg_graph.nodes[node]['label']
                
                # 保存处理后的 PDG
                nx.nx_agraph.write_dot(pdg_graph, pdg_path)
                
            except Exception as e:
                logging.warning(f"Failed to preprocess {pdg_file}: {e}")
        
        logging.info("✓ PDG preprocessing complete")


# 全局工作函数,用于多进程池
def process_single_task(args):
    """
    处理单个任务的工作函数(用于多进程)
    
    Args:
        args: (task_index, task, output_dir)
    
    Returns:
        (task_index, result)
    """
    task_index, task, output_dir = args
    
    # 重新配置日志(每个进程单独配置)
    import logging
    logging.basicConfig(
        level=logging.WARNING,  # 子进程使用WARNING级别,减少输出
        format='%(asctime)s - [Process %(process)d] - %(levelname)s - %(message)s'
    )
    
    # 创建临时的切片器实例
    joern_analyzer = JoernAnalyzer()
    
    project_name = task.get('project_name_with_version', 'unknown')
    file_path = task.get('file_path', 'unknown')
    target_line = task.get('line_number', 0)
    
    # 保留输入数据的所有字段
    result = dict(task)  # 复制所有输入字段
    result["status"] = "pending"
    
    temp_dir = None
    
    try:
        # 1. 加载源文件（直接路径优先，失败则在仓库中搜索）
        project_dir = os.path.join(config.REPOSITORY_DIR, project_name)
        full_path = _find_file_in_repo(project_dir, file_path)
        if not full_path:
            raise SingleFileSlicerException(f"Source file not found: {os.path.join(project_dir, file_path)}")
        
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            code_lines = f.readlines()
        
        # 2. 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="slice_")
        
        # 3. 使用 Joern 分析文件
        pdg_dir = joern_analyzer.analyze_file(full_path, temp_dir)
        
        # 4. 预处理 PDG
        cfg_dir = os.path.join(temp_dir, 'cfg')
        cpg_dir = os.path.join(temp_dir, 'cpg')
        if os.path.exists(cfg_dir) and os.path.exists(cpg_dir):
            joern_analyzer.preprocess_pdg(pdg_dir, cfg_dir, cpg_dir)
        
        # 5. 查找包含目标行的 PDG
        file_name = os.path.basename(file_path)
        pdg = None
        all_pdgs = []
        for pdg_file in os.listdir(pdg_dir):
            if not pdg_file.endswith('-pdg.dot'):
                continue
            pdg_path = os.path.join(pdg_dir, pdg_file)
            try:
                temp_pdg = PDG(pdg_path)
                if temp_pdg.filename and temp_pdg.filename.endswith(file_name):
                    all_pdgs.append(temp_pdg)
                    if temp_pdg.start_line and temp_pdg.end_line:
                        if temp_pdg.start_line <= target_line <= temp_pdg.end_line:
                            pdg = temp_pdg
                            break
            except:
                continue
        
        # 宽松匹配回退（与 _find_pdg_for_line 策略一致）
        if not pdg and all_pdgs:
            # 策略2：节点精确命中
            for temp_pdg in all_pdgs:
                if temp_pdg.has_node_at_line(target_line):
                    pdg = temp_pdg
                    break
            # 策略3：邻近节点最多
            if not pdg:
                best_count = 0
                for temp_pdg in all_pdgs:
                    count = temp_pdg.count_nodes_near_line(target_line, radius=200)
                    if count > best_count:
                        best_count = count
                        pdg = temp_pdg
        
        if not pdg:
            # 兜底：提取前后各 CONTEXT_SIZE 行上下文
            logging.warning(f"No PDG found for line {target_line}, falling back to context extraction")
            start_ln = max(1, target_line - config.CONTEXT_SIZE)
            end_ln = min(len(code_lines), target_line + config.CONTEXT_SIZE)
            context_lines_set = set(range(start_ln, end_ln + 1))
            sliced_code = "".join(code_lines[start_ln - 1:end_ln])
            result["status"] = "context_fallback"
            result["sliced_code"] = sliced_code
            result["complete_code"] = sliced_code
            result["slice_lines"] = list(context_lines_set)
            result["enhanced_slice_lines"] = list(context_lines_set)
            result["called_functions"] = []
            result["function_definitions"] = {}
            result["function_name"] = None
            result["function_start_line"] = None
            result["function_end_line"] = None
            result["metadata"] = {
                "slice_type": "context_extraction",
                "context_size": config.CONTEXT_SIZE,
                "extraction_reason": "no_pdg_found",
            }
            return (task_index, result)
        
        result["function_name"] = pdg.method_name
        result["function_start_line"] = pdg.start_line
        result["function_end_line"] = pdg.end_line
        
        # 6. 执行切片
        engine = SliceEngine(pdg)
        slice_nodes, metadata = engine.slice(target_line, rule_id=task.get('rule_id'))
        
        # 7. 提取切片行号
        slice_lines = {node.line_number for node in slice_nodes if node.line_number}
        
        # 8. AST 增强
        enhanced_lines = slice_lines
        ast_enhanced_success = False
        if config.ENABLE_AST_FIX:
            try:
                from ast_enhancer import enhance_slice_with_ast
                func_start_idx = (pdg.start_line or 1) - 1
                func_end_idx = (pdg.end_line or len(code_lines))
                func_code = "".join(code_lines[func_start_idx:func_end_idx])
                
                enhanced_lines = enhance_slice_with_ast(
                    source_code=func_code,
                    slice_lines=slice_lines,
                    language=config.LANGUAGE,
                    function_start_line=pdg.start_line or 1,
                    target_line=target_line,
                )
                ast_enhanced_success = len(enhanced_lines) > len(slice_lines)
            except:
                enhanced_lines = slice_lines
        
        # 9. 提取切片代码
        from code_extractor import extract_code_with_functions
        source_line_dict = {i + 1: line for i, line in enumerate(code_lines)}
        
        # 检测"无效切片"：警告行不在切片内，或函数体为空（仅含函数签名/空括号）
        def _is_trivial_slice(lines: Set[int], src: Dict[int, str], warn_line: int) -> bool:
            """
            判断切片是否对分析无价值：
            1. 警告行不在切片行集合中；或
            2. 切片覆盖的函数体内没有任何实质语句（空函数体）。
            """
            if warn_line not in lines:
                return True
            # 统计非空行（去掉空行、纯括号行、函数签名行）
            meaningful = 0
            for ln in lines:
                content = src.get(ln, '').strip()
                if content and content not in ('{', '}', '};') and not content.startswith('//'):
                    meaningful += 1
            # 少于 2 行实质内容视为无意义
            return meaningful < 2

        # 检测空切片或无效切片，优先使用 AST 变量追踪切片，最后才降级到上下文截取
        slice_is_empty = not enhanced_lines or len(enhanced_lines) == 0
        slice_is_trivial = (not slice_is_empty
                            and _is_trivial_slice(enhanced_lines, source_line_dict, target_line))
        if config.EMPTY_SLICE_FALLBACK and (slice_is_empty or slice_is_trivial):
            fallback_reason = "empty_pdg_slice" if slice_is_empty else "trivial_slice_no_warning_line"
            logging.warning(
                f"{'Empty' if slice_is_empty else 'Trivial'} slice detected for "
                f"{file_path}:{target_line} (reason={fallback_reason}), trying AST variable slice"
            )
            
            ast_var_lines = set()
            try:
                from code_extractor import ast_variable_slice
                ast_var_lines = ast_variable_slice(
                    source_lines=source_line_dict,
                    target_line=target_line,
                    function_start_line=pdg.start_line or max(1, target_line - 100),
                    function_end_line=pdg.end_line or min(len(code_lines), target_line + 100),
                    language=config.LANGUAGE,
                )
            except Exception as e:
                logging.warning(f"AST variable slice failed: {e}")
            
            if ast_var_lines:
                enhanced_lines = ast_var_lines
                metadata["slice_type"] = "ast_variable_slice"
                metadata["extraction_reason"] = f"{fallback_reason}_ast_fallback"
            else:
                # 最终降级：提取上下文(前后N行)
                start_line = max(1, target_line - config.CONTEXT_SIZE)
                end_line = min(len(code_lines), target_line + config.CONTEXT_SIZE)
                enhanced_lines = set(range(start_line, end_line + 1))
                metadata["slice_type"] = "context_extraction"
                metadata["context_size"] = config.CONTEXT_SIZE
                metadata["extraction_reason"] = fallback_reason
        else:
            metadata["slice_type"] = "pdg_slice"
        
        # 使用增强的代码提取（包含函数调用定义）
        extraction_result = extract_code_with_functions(
            slice_lines=enhanced_lines,
            source_lines=source_line_dict,
            warning_line=target_line,
            function_start_line=pdg.start_line,
            function_end_line=pdg.end_line,
            placeholder=config.PLACEHOLDER,
            extract_functions=config.EXTRACT_FUNCTION_CALLS,
            project_root=os.path.join(config.REPOSITORY_DIR, project_name),
            current_file_path=file_path
        )
        
        # 10. 构建结果
        result["status"] = "success"
        result["function_name"] = pdg.method_name
        result["sliced_code"] = extraction_result["sliced_code"]
        result["slice_lines"] = sorted(list(slice_lines))
        result["enhanced_slice_lines"] = sorted(list(enhanced_lines))
        result["metadata"] = metadata
        
        # 添加函数提取信息
        if config.EXTRACT_FUNCTION_CALLS:
            result["called_functions"] = sorted(list(extraction_result["called_functions"]))
            result["function_definitions"] = extraction_result["function_definitions"]
            result["complete_code"] = extraction_result["complete_code"]
            metadata["called_functions_count"] = len(extraction_result["called_functions"])
            metadata["extracted_functions_count"] = len(extraction_result["function_definitions"])
        
        metadata["original_slice_lines"] = len(slice_lines)
        metadata["enhanced_slice_lines"] = len(enhanced_lines)
        metadata["final_node_count"] = len(slice_nodes)
        metadata["ast_enhanced"] = ast_enhanced_success
        
    except SingleFileSlicerException as e:
        result["status"] = "error"
        result["error"] = str(e)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
    finally:
        # 清理临时目录
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
    
    return (task_index, result)


class SingleFileSlicer:
    """单文件切片器"""
    
    def __init__(self):
        self.joern_analyzer = JoernAnalyzer()
        self.tasks = self._load_tasks()
        self.checkpoint_data = self._load_checkpoint()
        self.processed_count = 0
        self.chunk_results = []  # 当前chunk的结果
        
        # 多进程共享数据
        self.manager = None
        self.lock = None
        self.shared_checkpoint = None
        self.shared_stats = None
    
    def _load_tasks(self) -> List[Dict]:
        """加载切片任务"""
        logging.info(f"Loading tasks from {config.DATA_JSON}")
        
        if not os.path.exists(config.DATA_JSON):
            logging.error(f"Data file not found: {config.DATA_JSON}")
            return []
        
        with open(config.DATA_JSON, 'r', encoding='utf-8') as f:
            tasks = json.load(f)
        
        logging.info(f"Loaded {len(tasks)} tasks")
        return tasks
    
    def _load_checkpoint(self) -> Dict:
        """加载断点信息"""
        if not config.ENABLE_CHECKPOINT:
            return {"processed_ids": [], "chunk_count": 0}
        
        if os.path.exists(config.CHECKPOINT_FILE):
            try:
                with open(config.CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                    checkpoint = json.load(f)
                # 兼容旧版本的 processed_indices
                if "processed_indices" in checkpoint and "processed_ids" not in checkpoint:
                    logging.warning("Converting old checkpoint format (indices) to new format (ids)")
                    checkpoint["processed_ids"] = []
                    checkpoint.pop("processed_indices", None)
                logging.info(f"Loaded checkpoint: {len(checkpoint.get('processed_ids', []))} tasks already processed")
                return checkpoint
            except Exception as e:
                logging.warning(f"Failed to load checkpoint: {e}")
        
        return {"processed_ids": [], "chunk_count": 0}
    
    def _save_checkpoint(self, processed_id: int):
        """保存断点信息 (使用任务id而非索引)
        
        注意: 只有在任务成功完成后才调用此方法，确保checkpoint记录的都是已完成的任务
        """
        if not config.ENABLE_CHECKPOINT:
            return
        
        if processed_id not in self.checkpoint_data["processed_ids"]:
            self.checkpoint_data["processed_ids"].append(processed_id)
        
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        
        # 使用临时文件+原子重命名，防止写入过程中程序崩溃导致文件损坏
        temp_file = config.CHECKPOINT_FILE + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.checkpoint_data, f, indent=2)
            # 原子性重命名
            os.replace(temp_file, config.CHECKPOINT_FILE)
        except Exception as e:
            logging.warning(f"Failed to save checkpoint: {e}")
            # 清理临时文件
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
    def _save_chunk(self, chunk_results: List[Dict], chunk_index: int):
        """保存一个chunk的结果"""
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        
        chunk_file = os.path.join(config.OUTPUT_DIR, f"slices_chunk_{chunk_index:04d}.json")
        
        try:
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk_results, f, indent=2, ensure_ascii=False)
            logging.info(f"✓ Saved chunk {chunk_index} ({len(chunk_results)} items) to {chunk_file}")
            
            # 更新checkpoint
            self.checkpoint_data["chunk_count"] = chunk_index
            
            # 保存简化的summary
            summary_file = os.path.join(config.OUTPUT_DIR, f"slices_chunk_{chunk_index:04d}_summary.json")
            summary = []
            for r in chunk_results:
                summary_item = {
                    "project_name_with_version": r.get("project_name_with_version"),
                    "file_path": r.get("file_path"),
                    "line_number": r.get("line_number"),
                    "status": r.get("status"),
                    "function_name": r.get("function_name"),
                    "slice_lines_count": len(r.get("slice_lines", [])),
                    "enhanced_lines_count": len(r.get("enhanced_slice_lines", []))
                }
                if r.get("status") == "error":
                    summary_item["error"] = r.get("error")
                summary.append(summary_item)
            
            with open(summary_file, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            logging.error(f"Failed to save chunk {chunk_index}: {e}")
    
    def _save_progress(self, current_id: int, total: int, processed_count: int, success: int, failed: int):
        """保存处理进度 (使用任务id而非索引)
        
        进度文件会更频繁更新，用于监控当前状态
        """
        progress = {
            "current_id": current_id,
            "total_tasks": total,
            "processed": processed_count,
            "success": success,
            "failed": failed,
            "progress_percentage": (processed_count / total * 100) if total > 0 else 0,
            "timestamp": json.dumps(None)  # Will be replaced below
        }
        
        # Add timestamp
        import datetime
        progress["timestamp"] = datetime.datetime.now().isoformat()
        
        # 使用临时文件+原子重命名，防止写入过程中程序崩溃导致文件损坏
        temp_file = config.PROGRESS_FILE + ".tmp"
        try:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)
            # 原子性重命名
            os.replace(temp_file, config.PROGRESS_FILE)
        except Exception as e:
            logging.warning(f"Failed to save progress: {e}")
            # 清理临时文件
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
    
    def _load_source_file(self, project_version: str, file_path: str) -> Tuple[str, List[str]]:
        """
        加载源代码文件。先尝试直接路径，若不存在则在仓库目录中按 basename 搜索。

        Returns:
            (完整文件路径, 代码行列表)
        """
        project_dir = os.path.join(config.REPOSITORY_DIR, project_version)
        full_path = _find_file_in_repo(project_dir, file_path)

        if not full_path:
            raise SingleFileSlicerException(
                f"Source file not found: {os.path.join(project_dir, file_path)}"
            )

        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            return full_path, lines
        except Exception as e:
            raise SingleFileSlicerException(f"Failed to read {full_path}: {e}")
    
    def _find_pdg_for_line(self, pdg_dir: str, target_line: int, file_name: str) -> Optional[PDG]:
        """
        在 PDG 目录中查找包含目标行的 PDG。
        
        查找策略（按优先级）：
        1. 精确匹配：PDG 的 METHOD 节点行范围 [start_line, end_line] 包含目标行
        2. 节点精确命中：PDG 中存在行号恰好等于目标行的节点
        3. 宽松匹配：PDG 中目标行附近（±200行）节点最多的 PDG
        """
        all_pdgs = []
        
        for pdg_file in os.listdir(pdg_dir):
            if not pdg_file.endswith('-pdg.dot'):
                continue
            
            pdg_path = os.path.join(pdg_dir, pdg_file)
            try:
                pdg = PDG(pdg_path)
                
                # 检查文件名
                if pdg.filename and not pdg.filename.endswith(file_name):
                    continue
                
                all_pdgs.append(pdg)
                
                # 策略1：精确行范围匹配
                if pdg.start_line and pdg.end_line:
                    if pdg.start_line <= target_line <= pdg.end_line:
                        logging.info(f"PDG found via exact range match: {pdg}")
                        return pdg
            except Exception as e:
                logging.debug(f"Failed to load {pdg_file}: {e}")
                continue
        
        if not all_pdgs:
            return None
        
        # 策略2：PDG 中存在精确在目标行的节点
        for pdg in all_pdgs:
            if pdg.has_node_at_line(target_line):
                logging.info(f"PDG found via exact node-line match: {pdg}")
                return pdg
        
        # 策略3：宽松匹配 —— 选择目标行附近节点最多的 PDG
        # 适用于 Joern 将宏展开函数识别为 <global> 或行范围记录不准确的场景
        best_pdg = None
        best_count = 0
        for pdg in all_pdgs:
            count = pdg.count_nodes_near_line(target_line, radius=200)
            if count > best_count:
                best_count = count
                best_pdg = pdg
        
        if best_pdg and best_count > 0:
            logging.warning(
                f"PDG found via relaxed match (nearest-nodes strategy): {best_pdg}, "
                f"{best_count} nodes within ±200 lines of target line {target_line}. "
                f"METHOD range: {best_pdg.start_line}-{best_pdg.end_line}"
            )
            return best_pdg
        
        return None
    
    def slice_one(self, task: Dict) -> Dict:
        """对单个任务执行切片"""
        project_name = task.get('project_name_with_version', 'unknown')
        file_path = task.get('file_path', 'unknown')
        target_line = task.get('line_number', 0)
        
        logging.info("\n" + "=" * 60)
        logging.info(f"Processing: {project_name} - {file_path}:{target_line}")
        
        # 保留输入数据的所有字段
        result = dict(task)  # 复制所有输入字段
        result["status"] = "pending"
        
        temp_dir = None
        
        try:
            # 1. 加载源文件
            full_path, code_lines = self._load_source_file(project_name, file_path)
            logging.info(f"Loaded source file: {len(code_lines)} lines")
            
            # 2. 创建临时目录
            temp_dir = tempfile.mkdtemp(prefix="slice_")
            logging.info(f"Created temp directory: {temp_dir}")
            
            # 3. 使用 Joern 分析文件
            pdg_dir = self.joern_analyzer.analyze_file(full_path, temp_dir)
            
            # 4. 预处理 PDG
            cfg_dir = os.path.join(temp_dir, 'cfg')
            cpg_dir = os.path.join(temp_dir, 'cpg')
            if os.path.exists(cfg_dir) and os.path.exists(cpg_dir):
                self.joern_analyzer.preprocess_pdg(pdg_dir, cfg_dir, cpg_dir)
            
            # 5. 查找包含目标行的 PDG
            file_name = os.path.basename(file_path)
            pdg = self._find_pdg_for_line(pdg_dir, target_line, file_name)
            
            if not pdg:
                # 兜底：提取前后各 CONTEXT_SIZE 行上下文
                logging.warning(f"No PDG found for line {target_line}, falling back to context extraction")
                start_ln = max(1, target_line - config.CONTEXT_SIZE)
                end_ln = min(len(code_lines), target_line + config.CONTEXT_SIZE)
                sliced_code = "".join(code_lines[start_ln - 1:end_ln])
                context_lines_set = list(range(start_ln, end_ln + 1))
                result["status"] = "context_fallback"
                result["sliced_code"] = sliced_code
                result["complete_code"] = sliced_code
                result["slice_lines"] = context_lines_set
                result["enhanced_slice_lines"] = context_lines_set
                result["called_functions"] = []
                result["function_definitions"] = {}
                result["function_name"] = None
                result["function_start_line"] = None
                result["function_end_line"] = None
                result["metadata"] = {
                    "slice_type": "context_extraction",
                    "context_size": config.CONTEXT_SIZE,
                    "extraction_reason": "no_pdg_found",
                }
                return result
            
            logging.info(f"Found PDG: {pdg}")
            result["function_name"] = pdg.method_name
            result["function_start_line"] = pdg.start_line
            result["function_end_line"] = pdg.end_line
            
            # 6. 执行切片，获取节点集
            engine = SliceEngine(pdg)
            slice_nodes, metadata = engine.slice(target_line, rule_id=task.get('rule_id'))
            
            logging.info(f"Slice engine returned {len(slice_nodes)} nodes.")
            
            # 7. 提取切片行号
            slice_lines = {node.line_number for node in slice_nodes if node.line_number}
            
            # 8. AST 增强（如果启用）
            enhanced_lines = slice_lines
            ast_enhanced_success = False
            if config.ENABLE_AST_FIX:
                try:
                    from ast_enhancer import enhance_slice_with_ast
                    # 提取函数代码（而不是整个文件）
                    func_start_idx = (pdg.start_line or 1) - 1
                    func_end_idx = (pdg.end_line or len(code_lines))
                    func_code = "".join(code_lines[func_start_idx:func_end_idx])
                    
                    enhanced_lines = enhance_slice_with_ast(
                        source_code=func_code,
                        slice_lines=slice_lines,
                        language=config.LANGUAGE,
                        function_start_line=pdg.start_line or 1,
                        target_line=target_line,
                    )
                    ast_enhanced_success = len(enhanced_lines) > len(slice_lines)
                    logging.info(f"AST enhancement: {len(slice_lines)} -> {len(enhanced_lines)} lines (added {len(enhanced_lines) - len(slice_lines)} lines)")
                except Exception as e:
                    logging.warning(f"AST enhancement failed, using original slice: {e}")
                    import traceback as _tb
                    logging.debug(_tb.format_exc())
                    enhanced_lines = slice_lines
            
            # 9. 提取切片代码
            from code_extractor import extract_code_with_functions
            
            # 构建源代码行字典（1-based）
            source_line_dict = {i + 1: line for i, line in enumerate(code_lines)}
            
            # 检测空切片，优先使用 AST 变量追踪切片，最后才降级到上下文截取
            if not enhanced_lines or len(enhanced_lines) == 0:
                logging.warning(f"Empty slice detected for {file_path}:{target_line}, trying AST variable slice")
                
                ast_var_lines: Set[int] = set()
                try:
                    from code_extractor import ast_variable_slice
                    ast_var_lines = ast_variable_slice(
                        source_lines=source_line_dict,
                        target_line=target_line,
                        function_start_line=pdg.start_line or max(1, target_line - 100),
                        function_end_line=pdg.end_line or min(len(code_lines), target_line + 100),
                        language=config.LANGUAGE,
                    )
                except Exception as e:
                    logging.warning(f"AST variable slice failed: {e}")
                
                if ast_var_lines:
                    enhanced_lines = ast_var_lines
                    metadata["slice_type"] = "ast_variable_slice"
                    metadata["extraction_reason"] = "empty_pdg_slice_ast_fallback"
                    logging.info(f"AST variable slice succeeded: {len(enhanced_lines)} lines")
                else:
                    # 最终降级：提取上下文(前后N行)
                    logging.warning(f"AST variable slice also failed, using context extraction fallback")
                    context_size = 30
                    start_line = max(1, target_line - context_size)
                    end_line = min(len(code_lines), target_line + context_size)
                    enhanced_lines = set(range(start_line, end_line + 1))
                    metadata["slice_type"] = "context_extraction"
                    metadata["context_size"] = context_size
                    metadata["extraction_reason"] = "empty_pdg_slice"
            else:
                metadata["slice_type"] = "pdg_slice"
            
            # 使用增强的代码提取（包含函数调用定义）
            extraction_result = extract_code_with_functions(
                slice_lines=enhanced_lines,
                source_lines=source_line_dict,
                warning_line=target_line,
                function_start_line=pdg.start_line,
                function_end_line=pdg.end_line,
                placeholder=config.PLACEHOLDER,
                extract_functions=config.EXTRACT_FUNCTION_CALLS,
                project_root=os.path.join(config.REPOSITORY_DIR, project_name),
                current_file_path=file_path
            )
            
            # 10. 构建结果
            result["status"] = "success"
            result["function_name"] = pdg.method_name
            result["sliced_code"] = extraction_result["sliced_code"]
            result["slice_lines"] = sorted(list(slice_lines))
            result["enhanced_slice_lines"] = sorted(list(enhanced_lines))
            result["metadata"] = metadata
            
            # 添加函数提取信息
            if config.EXTRACT_FUNCTION_CALLS:
                result["called_functions"] = sorted(list(extraction_result["called_functions"]))
                result["function_definitions"] = extraction_result["function_definitions"]
                result["complete_code"] = extraction_result["complete_code"]
                metadata["called_functions_count"] = len(extraction_result["called_functions"])
                metadata["extracted_functions_count"] = len(extraction_result["function_definitions"])
            
            # 更新元数据
            metadata["original_slice_lines"] = len(slice_lines)
            metadata["enhanced_slice_lines"] = len(enhanced_lines)
            metadata["final_node_count"] = len(slice_nodes)
            metadata["ast_enhanced"] = ast_enhanced_success
            
            logging.info(f"✓ Slice completed successfully")
            logging.info(f"  Function: {metadata.get('function_name', 'N/A')}")
            logging.info(f"  Final Lines: {metadata.get('total_slice_lines', 0)}")
            
        except SingleFileSlicerException as e:
            result["status"] = "error"
            result["error"] = str(e)
            logging.error(f"Slice failed: {e}")
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
            logging.error(f"Unexpected error: {e}")
            logging.error(traceback.format_exc())
        finally:
            # 清理临时目录
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logging.debug(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    logging.warning(f"Failed to clean up {temp_dir}: {e}")
        
        return result
    
    def slice_all(self) -> List[Dict]:
        """对所有任务执行切片（支持断点续传和分chunk保存）"""
        chunk_results = []
        chunk_index = self.checkpoint_data.get("chunk_count", 0) + 1
        
        processed_ids = set(self.checkpoint_data.get("processed_ids", []))
        success_count = 0
        failed_count = 0
        
        logging.info(f"\nStarting batch slicing for {len(self.tasks)} tasks...")
        if processed_ids:
            logging.info(f"Resuming from checkpoint: {len(processed_ids)} tasks already processed")
        
        for i, task in enumerate(self.tasks):
            task_id = task.get("id")
            if task_id is None:
                logging.warning(f"Task at index {i} has no 'id' field, skipping")
                continue
            
            # 跳过已处理的任务
            if task_id in processed_ids:
                logging.debug(f"Skipping already processed task id={task_id} ({i+1}/{len(self.tasks)})")
                continue
            
            logging.info(f"\n[{i+1}/{len(self.tasks)}] ID={task_id} (Success: {success_count}, Failed: {failed_count})")
            
            # 标记任务开始处理（在进度文件中记录，但不在checkpoint中）
            processed_count = len(processed_ids) + success_count + failed_count
            self._save_progress(task_id, len(self.tasks), processed_count, success_count, failed_count)
            
            # 执行切片
            result = self.slice_one(task)
            
            # 统计结果
            if result['status'] == 'success':
                success_count += 1
            else:
                failed_count += 1
            
            # 添加到当前chunk
            chunk_results.append(result)
            
            # 只有任务完成后（无论成功或失败），才保存到checkpoint
            # 这样如果程序在处理过程中崩溃，重启后会重新处理这个任务
            self._save_checkpoint(task_id)
            
            # 更新最终进度
            processed_count = len(processed_ids) + success_count + failed_count
            self._save_progress(task_id, len(self.tasks), processed_count, success_count, failed_count)
            
            # 如果当前chunk已满，保存并开始新chunk
            if len(chunk_results) >= config.CHUNK_SIZE:
                self._save_chunk(chunk_results, chunk_index)
                chunk_results = []
                chunk_index += 1
        
        # 保存最后一个未满的chunk
        if chunk_results:
            self._save_chunk(chunk_results, chunk_index)
        
        # 统计
        total_processed = success_count + failed_count
        
        logging.info(f"\n{'='*60}")
        logging.info(f"Batch slicing completed!")
        logging.info(f"  Total: {len(self.tasks)}")
        logging.info(f"  Processed: {total_processed}")
        logging.info(f"  Success: {success_count} ({success_count/total_processed*100:.1f}%)" if total_processed > 0 else "  Success: 0")
        logging.info(f"  Failed: {failed_count} ({failed_count/total_processed*100:.1f}%)" if total_processed > 0 else "  Failed: 0")
        logging.info(f"  Saved in {chunk_index} chunks")
        
        # 自动合并所有chunk文件
        logging.info(f"\n{'='*60}")
        logging.info("Merging all chunk files...")
        self.merge_chunks()
        
        return []  # 不再返回所有结果，因为已经分chunk保存
    
    def slice_all_multiprocess(self) -> List[Dict]:
        """使用多进程并行处理所有任务"""
        from multiprocessing import Pool, Manager
        
        chunk_results = []
        chunk_index = self.checkpoint_data.get("chunk_count", 0) + 1
        
        processed_ids = set(self.checkpoint_data.get("processed_ids", []))
        success_count = 0
        failed_count = 0
        
        logging.info(f"\nStarting batch slicing with {config.NUM_PROCESSES} processes...")
        logging.info(f"Total tasks: {len(self.tasks)}")
        if processed_ids:
            logging.info(f"Resuming from checkpoint: {len(processed_ids)} tasks already processed")
        
        # 准备待处理的任务列表
        tasks_to_process = []
        for i, task in enumerate(self.tasks):
            task_id = task.get("id")
            if task_id is None:
                logging.warning(f"Task at index {i} has no 'id' field, skipping")
                continue
            if task_id not in processed_ids:
                tasks_to_process.append((i, task, config.OUTPUT_DIR))
        
        if not tasks_to_process:
            logging.info("All tasks already completed!")
            self.merge_chunks()
            return []
        
        logging.info(f"Tasks to process: {len(tasks_to_process)}")
        
        # 使用进程池处理
        start_time = time.time()
        processed_count = 0
        
        try:
            with Pool(processes=config.NUM_PROCESSES) as pool:
                # 使用 imap_unordered 获取结果,按完成顺序返回
                for task_index, result in pool.imap_unordered(process_single_task, tasks_to_process):
                    # 获取任务ID
                    task = self.tasks[task_index]
                    task_id = task.get("id")
                    
                    processed_count += 1
                    
                    # 统计结果
                    if result['status'] == 'success':
                        success_count += 1
                    else:
                        failed_count += 1
                    
                    # 添加到当前chunk
                    chunk_results.append(result)
                    
                    # 保存断点
                    self._save_checkpoint(task_id)
                    
                    # 保存进度
                    total_processed = len(processed_ids) + processed_count
                    self._save_progress(task_id, len(self.tasks), total_processed, success_count, failed_count)
                    
                    # 显示进度
                    elapsed = time.time() - start_time
                    avg_time = elapsed / processed_count if processed_count > 0 else 0
                    remaining = len(tasks_to_process) - processed_count
                    eta = avg_time * remaining
                    
                    logging.info(
                        f"[{total_processed}/{len(self.tasks)}] ID={task_id} "
                        f"Success: {success_count}, Failed: {failed_count}, "
                        f"Speed: {avg_time:.1f}s/task, ETA: {eta/3600:.1f}h"
                    )
                    
                    # 如果当前chunk已满,保存并开始新chunk
                    if len(chunk_results) >= config.CHUNK_SIZE:
                        self._save_chunk(chunk_results, chunk_index)
                        chunk_results = []
                        chunk_index += 1
        
        except KeyboardInterrupt:
            logging.warning("\nProcess interrupted by user")
            # 保存当前已完成的chunk
            if chunk_results:
                self._save_chunk(chunk_results, chunk_index)
            raise
        
        # 保存最后一个未满的chunk
        if chunk_results:
            self._save_chunk(chunk_results, chunk_index)
        
        # 统计
        total_processed = success_count + failed_count
        elapsed = time.time() - start_time
        
        logging.info(f"\n{'='*60}")
        logging.info(f"Batch slicing completed!")
        logging.info(f"  Total: {len(self.tasks)}")
        logging.info(f"  Processed this run: {total_processed}")
        logging.info(f"  Success: {success_count} ({success_count/total_processed*100:.1f}%)" if total_processed > 0 else "  Success: 0")
        logging.info(f"  Failed: {failed_count} ({failed_count/total_processed*100:.1f}%)" if total_processed > 0 else "  Failed: 0")
        logging.info(f"  Time elapsed: {elapsed/3600:.2f} hours")
        logging.info(f"  Average speed: {elapsed/total_processed:.1f} seconds/task" if total_processed > 0 else "")
        logging.info(f"  Saved in {chunk_index} chunks")
        
        # 自动合并所有chunk文件
        logging.info(f"\n{'='*60}")
        logging.info("Merging all chunk files...")
        self.merge_chunks()
        
        return []
    
    def save_results(self, results: List[Dict]):
        """
        合并所有chunk文件并保存最终结果（按ID排序）
        注意：由于使用了分chunk保存，这个方法主要用于合并已有的chunk文件
        """
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        
        # 如果没有传入results，尝试从chunk文件加载
        if not results:
            logging.info("Loading results from chunk files...")
            results = self._load_all_chunks()
        
        if not results:
            logging.warning("No results to save")
            return
        
        # 按ID排序（如果有id字段）
        results_with_id = [r for r in results if 'id' in r]
        results_without_id = [r for r in results if 'id' not in r]
        
        if results_with_id:
            results_with_id.sort(key=lambda x: x['id'])
            logging.info(f"Sorted {len(results_with_id)} results by ID")
        
        if results_without_id:
            logging.warning(f"Warning: {len(results_without_id)} results don't have 'id' field")
        
        # 合并：有id的在前（已排序），无id的在后
        results = results_with_id + results_without_id
        
        output_path = config.OUTPUT_JSON
        logging.info(f"\nSaving merged results to {output_path}")
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2, ensure_ascii=False)
            
            logging.info(f"✓ Results saved successfully ({len(results)} items)")
        except Exception as e:
            logging.error(f"Failed to save results: {e}")
            return
        
        # 保存简化版本（也按ID排序）
        summary_path = output_path.replace('.json', '_summary.json')
        summary = []
        for r in results:
            summary_item = {
                "id": r.get("id"),
                "project_name_with_version": r.get("project_name_with_version"),
                "file_path": r.get("file_path"),
                "line_number": r.get("line_number"),
                "status": r.get("status"),
                "function_name": r.get("function_name"),
                "slice_lines_count": len(r.get("slice_lines", [])),
                "enhanced_lines_count": len(r.get("enhanced_slice_lines", [])),
                "metadata": r.get("metadata", {})
            }
            if r.get("status") == "error":
                summary_item["error"] = r.get("error")
            summary.append(summary_item)
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logging.info(f"✓ Summary saved to {summary_path}")
        
        # 生成LLM专用的精简版本（不含label）
        llm_path = output_path.replace('.json', '_for_llm.json')
        llm_results = []
        for r in results:
            llm_item = {
                "id": r.get("id"),
                "tool_name": r.get("tool_name"),
                "project_name_with_version": r.get("project_name_with_version"),
                "project_version": r.get("project_version"),
                "line_number": r.get("line_number"),
                "function_name": r.get("function_name"),
                "rule_id": r.get("rule_id"),
                "message": r.get("message"),
                "sliced_code": r.get("complete_code") or r.get("sliced_code")
            }
            llm_results.append(llm_item)
        
        with open(llm_path, 'w', encoding='utf-8') as f:
            json.dump(llm_results, f, indent=2, ensure_ascii=False)
        
        logging.info(f"✓ LLM format saved to {llm_path}")
        
        # 生成LLM专用的精简版本（含label）
        llm_label_path = output_path.replace('.json', '_for_llm_with_label.json')
        llm_label_results = []
        for r in results:
            llm_label_item = {
                "id": r.get("id"),
                "tool_name": r.get("tool_name"),
                "project_name_with_version": r.get("project_name_with_version"),
                "project_version": r.get("project_version"),
                "line_number": r.get("line_number"),
                "function_name": r.get("function_name"),
                "rule_id": r.get("rule_id"),
                "message": r.get("message"),
                "sliced_code": r.get("complete_code") or r.get("sliced_code"),
                "label": r.get("label")
            }
            llm_label_results.append(llm_label_item)
        
        with open(llm_label_path, 'w', encoding='utf-8') as f:
            json.dump(llm_label_results, f, indent=2, ensure_ascii=False)
        
        logging.info(f"✓ LLM format with label saved to {llm_label_path}")
    
    def _load_all_chunks(self) -> List[Dict]:
        """加载所有chunk文件并合并，按ID排序"""
        all_results = []
        chunk_files = sorted([f for f in os.listdir(config.OUTPUT_DIR) 
                             if f.startswith('slices_chunk_') and f.endswith('.json') 
                             and '_summary' not in f])
        
        logging.info(f"Found {len(chunk_files)} chunk files")
        
        for chunk_file in chunk_files:
            chunk_path = os.path.join(config.OUTPUT_DIR, chunk_file)
            try:
                with open(chunk_path, 'r', encoding='utf-8') as f:
                    chunk_data = json.load(f)
                all_results.extend(chunk_data)
                logging.info(f"  Loaded {chunk_file}: {len(chunk_data)} items")
            except Exception as e:
                logging.warning(f"  Failed to load {chunk_file}: {e}")
        
        # 按任务ID排序
        if all_results:
            # 先检查所有结果是否都有id字段
            results_with_id = [r for r in all_results if 'id' in r]
            results_without_id = [r for r in all_results if 'id' not in r]
            
            if results_without_id:
                logging.warning(f"Warning: {len(results_without_id)} results don't have 'id' field")
            
            # 对有id的结果按id排序
            if results_with_id:
                results_with_id.sort(key=lambda x: x['id'])
                logging.info(f"✓ Sorted {len(results_with_id)} results by ID")
            
            # 合并：有id的在前（已排序），无id的在后
            all_results = results_with_id + results_without_id
        
        return all_results
    
    def merge_chunks(self, delete_chunks: bool = True):
        """合并所有chunk文件为最终结果文件
        
        Args:
            delete_chunks: 是否在合并后删除chunk文件（默认True）
        """
        logging.info("\nMerging all chunk files...")
        results = self._load_all_chunks()
        
        if not results:
            logging.warning("No chunk files found to merge")
            return
        
        # 保存合并结果
        self.save_results(results)
        logging.info(f"✓ Merged {len(results)} results from chunk files")
        
        # 删除chunk文件
        if delete_chunks:
            self._delete_chunk_files()
    
    def _delete_chunk_files(self):
        """删除所有chunk文件和对应的summary文件"""
        logging.info("\nCleaning up chunk files...")
        
        # 查找所有chunk文件（包括主文件和summary文件）
        chunk_files = [f for f in os.listdir(config.OUTPUT_DIR) 
                      if f.startswith('slices_chunk_') and f.endswith('.json')]
        
        deleted_count = 0
        failed_count = 0
        
        for chunk_file in chunk_files:
            chunk_path = os.path.join(config.OUTPUT_DIR, chunk_file)
            try:
                os.remove(chunk_path)
                deleted_count += 1
                logging.debug(f"  Deleted: {chunk_file}")
            except Exception as e:
                failed_count += 1
                logging.warning(f"  Failed to delete {chunk_file}: {e}")
        
        if deleted_count > 0:
            logging.info(f"✓ Deleted {deleted_count} chunk files")
        if failed_count > 0:
            logging.warning(f"✗ Failed to delete {failed_count} chunk files")
    
    def get_progress_info(self) -> Dict:
        """获取处理进度信息"""
        if os.path.exists(config.PROGRESS_FILE):
            try:
                with open(config.PROGRESS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logging.warning(f"Failed to load progress: {e}")
        return {}
    
    def clear_checkpoint(self):
        """清除断点信息（重新开始处理）"""
        if os.path.exists(config.CHECKPOINT_FILE):
            try:
                os.remove(config.CHECKPOINT_FILE)
                logging.info("✓ Checkpoint cleared")
            except Exception as e:
                logging.warning(f"Failed to clear checkpoint: {e}")
        
        if os.path.exists(config.PROGRESS_FILE):
            try:
                os.remove(config.PROGRESS_FILE)
                logging.info("✓ Progress file cleared")
            except Exception as e:
                logging.warning(f"Failed to clear progress: {e}")
        
        self.checkpoint_data = {"processed_ids": [], "chunk_count": 0}


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Single File Slicer for C/C++ Projects')
    parser.add_argument('--clear', action='store_true', 
                       help='Clear checkpoint and restart from beginning')
    parser.add_argument('--progress', action='store_true',
                       help='Show current progress')
    parser.add_argument('--chunk-size', type=int, default=None,
                       help='Override default chunk size')
    parser.add_argument('--processes', type=int, default=None,
                       help='Number of parallel processes (default: 3)')
    parser.add_argument('--no-multiprocess', action='store_true',
                       help='Disable multiprocessing, run in single process')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Single File Slicer for C/C++ Projects")
    print("=" * 60)
    
    try:
        slicer = SingleFileSlicer()
        
        # 显示进度
        if args.progress:
            progress = slicer.get_progress_info()
            if progress:
                print(f"\nCurrent Progress:")
                print(f"  Processed: {progress.get('processed', 0)}/{progress.get('total_tasks', 0)}")
                print(f"  Progress: {progress.get('progress_percentage', 0):.1f}%")
                print(f"  Success: {progress.get('success', 0)}")
                print(f"  Failed: {progress.get('failed', 0)}")
                print(f"  Last Update: {progress.get('timestamp', 'N/A')}")
            else:
                print("\nNo progress information available")
            return 0
        
        # 清除断点
        if args.clear:
            print("\nClearing checkpoint...")
            slicer.clear_checkpoint()
        
        # 设置chunk大小
        if args.chunk_size:
            config.CHUNK_SIZE = args.chunk_size
            print(f"\nChunk size set to: {config.CHUNK_SIZE}")
        
        # 设置进程数
        if args.processes:
            config.NUM_PROCESSES = args.processes
        
        # 设置是否启用多进程
        use_multiprocess = config.ENABLE_MULTIPROCESSING and not args.no_multiprocess
        
        # 执行切片
        print(f"\nConfiguration:")
        print(f"  Chunk Size: {config.CHUNK_SIZE}")
        print(f"  Checkpoint Enabled: {config.ENABLE_CHECKPOINT}")
        print(f"  AST Enhancement: {config.ENABLE_AST_FIX}")
        print(f"  Multiprocessing: {'Enabled' if use_multiprocess else 'Disabled'}")
        if use_multiprocess:
            print(f"  Parallel Processes: {config.NUM_PROCESSES}")
        
        # 执行切片 (完成后会自动合并chunk)
        if use_multiprocess:
            slicer.slice_all_multiprocess()
        else:
            slicer.slice_all()
        
        print("\n" + "=" * 60)
        print("Done!")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        print("Progress has been saved. Run again to resume from checkpoint.")
        return 1
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

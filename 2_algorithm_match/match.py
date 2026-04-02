import json
import os
import hashlib
from typing import List, Dict, Tuple, Optional
import difflib
import re

class Matcher:
    """
    警告匹配系统 - 跨版本追踪静态分析警告
    
    【核心目的】
    追踪父版本的警告在子版本中的去向，区分真实问题和误报。
    
    【匹配策略】
    采用多层渐进式匹配算法（优先级从高到低）：

    1. 精确匹配: 相同文件、相同行号
    2. 位置匹配: 基于diff的相对位置匹配（容忍行号变化）
    3. 片段匹配: 基于代码片段相似度匹配（容忍代码变动）
    4. 哈希匹配: 基于代码token哈希匹配（容忍变量重命名）
    """
    
    def __init__(self, matching_threshold: int = 3, context_lines: int = 2, 
                 snippet_similarity: float = 0.8, hash_size: int = 30):
        self.MATCHING_THRESHOLD = matching_threshold  # 位置匹配阈值
        self.CONTEXT_LINES = context_lines          # 片段匹配上下文行数
        self.SNIPPET_SIMILARITY = snippet_similarity  # 片段相似度阈值
        self.HASH_SIZE = hash_size                  # 哈希匹配的token大小
        
        self.match_stats = {
            'exact': 0,
            'location': 0, 
            'snippet': 0,
            'hash': 0
        }

    def _resolve_repo_dir(self, project_name_with_version: str) -> Optional[str]:
        """将 project_name_with_version 解析为实际的仓库目录路径。
        
        支持三种命名格式：
        - 下划线格式（curl）：curl-8_11_1 → input/repository/curl-8_11_1
        - 点格式（ffmpeg等）：ffmpeg-6_0 → input/repository/ffmpeg-6.0
        - 双前缀格式（openssl）：openssl-3_2_1 → input/repository/openssl-openssl-3.2.1
        """
        base = os.path.join('input', 'repository')

        # 尝试精确匹配（如 curl-8_11_1）
        candidate = os.path.join(base, project_name_with_version)
        if os.path.isdir(candidate):
            return candidate

        parts = project_name_with_version.split('-', 1)
        if len(parts) == 2:
            project, version_underscored = parts
            version_dots = version_underscored.replace('_', '.')

            # 尝试点格式（如 ffmpeg-6.0）
            candidate = os.path.join(base, f"{project}-{version_dots}")
            if os.path.isdir(candidate):
                return candidate

            # 尝试双前缀格式（如 openssl-openssl-3.2.1）
            candidate = os.path.join(base, f"{project}-{project}-{version_dots}")
            if os.path.isdir(candidate):
                return candidate

        return None

    def get_file_content(self, project_name_with_version: str, relative_path: str) -> Optional[str]:
        """获取文件内容"""
        repo_dir = self._resolve_repo_dir(project_name_with_version)
        if not repo_dir:
            return None
        file_path = os.path.join(repo_dir, relative_path)
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except FileNotFoundError:
            return None
        except Exception:
            return None
    
    def is_similar_file(self, path1: str, path2: str) -> bool:
        """判断文件路径是否相似"""
        file1 = os.path.basename(path1)
        file2 = os.path.basename(path2)
        
        if file1 == file2:
            return True
        
        norm1 = path1.replace('\\', '/').lower()
        norm2 = path2.replace('\\', '/').lower()
        
        if norm1 == norm2:
            return True
            
        if norm1.endswith(norm2) or norm2.endswith(norm1):
            return True
            
        return False
    
    #精确匹配算法
    def exact_matching(self, alarm1: Dict, alarm2: Dict) -> bool:

        file1 = alarm1['file_path']
        file2 = alarm2['file_path']
        
        if not self.is_similar_file(file1, file2):
            return False
        
        return alarm1.get('line_number', 0) == alarm2.get('line_number', 0)
    
    def find_exactly_matching_alarm(self, parent_alarm: Dict, child_alarms: List[Dict]) -> List[Dict]:
        """查找精确匹配的警告"""
        return [child for child in child_alarms if self.exact_matching(parent_alarm, child)]
    
    #位置匹配算法（基于diff映射）
    def _get_diff_matches(self, old_lines: List[str], new_lines: List[str]) -> List[Tuple[int, int]]:

        #获取diff匹配的行对,使用difflib.SequenceMatcher找到完全相同的行,只返回完全匹配的行对

        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        matches = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for offset in range(i2 - i1):
                    old_line = i1 + offset + 1  
                    new_line = j1 + offset + 1
                    matches.append((old_line, new_line))
        
        return matches
    
    def _find_closest_match(self, line_number: int, matches: List[Tuple[int, int]], 
                          version: str = 'old') -> Optional[int]:

        #查找给定行号最近的匹配行

        if not matches:
            return None
        
        closest_distance = float('inf')
        closest_line = None
        
        for old_line, new_line in matches:
            if version == 'old':
                distance = abs(old_line - line_number)
                if distance < closest_distance:
                    closest_distance = distance
                    closest_line = old_line
            else:  # version == 'new'
                distance = abs(new_line - line_number)
                if distance < closest_distance:
                    closest_distance = distance
                    closest_line = new_line
        
        return closest_line
    
    def location_based_matching_with_diff(self, parent_alarm: Dict, child_alarm: Dict,
                                          diff_matches: List[Tuple[int, int]]) -> bool:
        """基于预计算 diff 的位置匹配算法（每文件对只计算一次 diff）。"""
        if not diff_matches:
            return False

        parent_line = parent_alarm.get('line_number', 0)
        child_line = child_alarm.get('line_number', 0)

        parent_closest = self._find_closest_match(parent_line, diff_matches, 'old')
        child_closest = self._find_closest_match(child_line, diff_matches, 'new')

        if not parent_closest or not child_closest:
            return False

        parent_offset = parent_line - parent_closest
        child_offset = child_line - child_closest
        return abs(parent_offset - child_offset) <= self.MATCHING_THRESHOLD

    def location_based_matching(self, parent_alarm: Dict, child_alarm: Dict, 
                              parent_content: str, child_content: str) -> bool:
        
        #基于位置的匹配算法

        file1 = parent_alarm['file_path']
        file2 = child_alarm['file_path']
        
        if not self.is_similar_file(file1, file2):
            return False
        
        if not parent_content or not child_content:
            return False
        
        parent_line = parent_alarm.get('line_number', 0)
        child_line = child_alarm.get('line_number', 0)
        
        # 获取diff匹配
        parent_lines = parent_content.split('\n')
        child_lines = child_content.split('\n')
        matches = self._get_diff_matches(parent_lines, child_lines)
        
        if not matches:
            return False
        
        # 查找最近的匹配行
        parent_closest = self._find_closest_match(parent_line, matches, 'old')
        child_closest = self._find_closest_match(child_line, matches, 'new')
        
        if not parent_closest or not child_closest:
            return False
        
        # 计算偏移
        parent_offset = parent_line - parent_closest
        child_offset = child_line - child_closest
        
        # 判断偏移差异
        return abs(parent_offset - child_offset) <= self.MATCHING_THRESHOLD
    
    def find_location_based_matching_alarms(self, parent_alarm: Dict, child_alarms: List[Dict], 
                                          parent_content: str, child_content: str) -> List[Dict]:
        """查找基于位置匹配的警告"""
        if not parent_content or not child_content:
            return []
        
        return [child for child in child_alarms 
                if self.location_based_matching(parent_alarm, child, parent_content, child_content)]
    
    #基于代码片段的匹配算法（支持相似度）
    def get_code_snippet(self, content: str, line_number: int) -> Optional[str]:
        #获取代码片段 - 基于警告行及其上下文
        if not content:
            return None
        
        lines = content.split('\n')
        total_lines = len(lines)
        
        if line_number < 1 or line_number > total_lines:
            return None
        
        start_line = max(1, line_number - self.CONTEXT_LINES)
        end_line = min(total_lines, line_number + self.CONTEXT_LINES)
        
        snippet_lines = lines[start_line-1:end_line]
        
        # 移除共同缩进
        min_indent = float('inf')
        for line in snippet_lines:
            if line.strip():
                indent = len(line) - len(line.lstrip())
                min_indent = min(min_indent, indent)
        
        normalized_lines = []
        for line in snippet_lines:
            if line.strip() and min_indent != float('inf') and len(line) >= min_indent:
                normalized_lines.append(line[min_indent:])
            else:
                normalized_lines.append(line)
        
        return '\n'.join(normalized_lines)
    
    def get_code_line(self, content: str, line_number: int) -> Optional[str]:
        #获取指定行号的代码行
        if not content:
            return None
        
        lines = content.split('\n')
        total_lines = len(lines)
        
        if line_number < 1 or line_number > total_lines:
            return None
        
        return lines[line_number - 1]
    
    def normalize_code(self, code: str) -> str:
        #规范化代码：移除注释和空白
        if not code:
            return ""
        
        code = re.sub(r'#.*$', '', code, flags=re.MULTILINE)
        
        lines = code.split('\n')
        normalized_lines = []
        
        for line in lines:
            trimmed_line = line.strip()
            if trimmed_line:
                normalized_lines.append(trimmed_line)
        
        return '\n'.join(normalized_lines)
    
    def calculate_similarity(self, snippet1: str, snippet2: str) -> float:
        #计算两个代码片段的相似度
        if not snippet1 or not snippet2:
            return 0.0
        
        norm1 = self.normalize_code(snippet1)
        norm2 = self.normalize_code(snippet2)
        
        if not norm1 or not norm2:
            return 0.0
        
        matcher = difflib.SequenceMatcher(None, norm1, norm2)
        return matcher.ratio()
    
    def snippet_based_matching(self, parent_alarm: Dict, child_alarm: Dict, 
                             parent_content: str, child_content: str) -> bool:
        #基于代码片段的匹配算法，支持相似度匹配
        parent_snippet = self.get_code_snippet(parent_content, parent_alarm.get('line_number', 0))
        child_snippet = self.get_code_snippet(child_content, child_alarm.get('line_number', 0))
        
        if not parent_snippet or not child_snippet:
            return False
        
        similarity = self.calculate_similarity(parent_snippet, child_snippet)
        return similarity >= self.SNIPPET_SIMILARITY
    
    def find_snippet_based_matching_alarms(self, parent_alarm: Dict, child_alarms: List[Dict], 
                                          parent_content: str, child_content: str) -> List[Dict]:
        #查找基于代码片段匹配的警告
        if not parent_content or not child_content:
            return []
        
        return [child for child in child_alarms 
                if self.snippet_based_matching(parent_alarm, child, parent_content, child_content)]
    
    #基于哈希的匹配算法
    def _split_into_tokens(self, text: str) -> List[str]:
        #将文本分割为token
        if not text:
            return []
        
        #使用正则表达式分割为token（包括字母数字和下划线）
        tokens = re.findall(r'\w+', text)
        return tokens
    
    def _hash_first_tokens(self, text: str) -> str:
        #计算前N个token的哈希值
        tokens = self._split_into_tokens(text)
        
        if not tokens:
            return ""
        
        #取前N个token，如果不足则取全部
        first_tokens = tokens[:self.HASH_SIZE]
        first_text = ' '.join(first_tokens)
        
        return hashlib.md5(first_text.encode()).hexdigest()
    
    def _hash_last_tokens(self, text: str) -> str:
        """计算后N个token的哈希值"""
        tokens = self._split_into_tokens(text)
        
        if not tokens:
            return ""
        
        #取后N个token，如果不足则取全部
        last_tokens = tokens[-self.HASH_SIZE:] if len(tokens) > self.HASH_SIZE else tokens
        last_text = ' '.join(last_tokens)
        
        return hashlib.md5(last_text.encode()).hexdigest()
    
    def hash_based_matching(self, parent_alarm: Dict, child_alarm: Dict, 
                          parent_content: str, child_content: str) -> bool:
       
        #获取警告所在行的代码
        parent_line = self.get_code_line(parent_content, parent_alarm.get('line_number', 0))
        child_line = self.get_code_line(child_content, child_alarm.get('line_number', 0))
        
        if not parent_line or not child_line:
            return False
        
        #计算前后token的哈希值
        parent_first_hash = self._hash_first_tokens(parent_line)
        parent_last_hash = self._hash_last_tokens(parent_line)
        
        child_first_hash = self._hash_first_tokens(child_line)
        child_last_hash = self._hash_last_tokens(child_line)
        
        # 比较哈希值（只要有一个相同就认为匹配）
        return (parent_first_hash == child_first_hash) or (parent_last_hash == child_last_hash)
    
    def find_hash_based_matching_alarms(self, parent_alarm: Dict, child_alarms: List[Dict], 
                                      parent_content: str, child_content: str) -> List[Dict]:
        #查找基于哈希匹配的警告
        if not parent_content or not child_content:
            return []
        
        return [child for child in child_alarms 
                if self.hash_based_matching(parent_alarm, child, parent_content, child_content)]
    
    def match_warnings_between_versions(self, 
                                      parent_warnings: List[Dict], 
                                      child_warnings: List[Dict]) -> Dict:
        """
        匹配两个版本间的警告。
        返回一个字典，包含 'matched_pairs' 和 'unmatched_parent'。

        性能优化：对每个文件对，只读取一次文件内容、只计算一次 diff，
        然后对该文件内所有告警复用这些结果。
        """
        
        parent_alarms = parent_warnings.copy()
        child_alarms = child_warnings.copy()
        
        # 用于跟踪已匹配的子告警，避免重复匹配（使用 id 而非 list index）
        child_matched_ids = set()
        # 快速查找：child alarm id → object
        child_by_id = {w['id']: w for w in child_alarms}
        
        matched_pairs = []
        unmatched_parent = []
        
        # 按文件对告警进行分组
        warnings_by_file_parent: Dict[str, List[Dict]] = {}
        for w in parent_alarms:
            warnings_by_file_parent.setdefault(w['file_path'], []).append(w)

        warnings_by_file_child: Dict[str, List[Dict]] = {}
        for w in child_alarms:
            warnings_by_file_child.setdefault(w['file_path'], []).append(w)

        # 遍历父版本中涉及的文件
        for file_path, pa_group in warnings_by_file_parent.items():
            if file_path not in warnings_by_file_child:
                unmatched_parent.extend(pa_group)
                continue

            ca_group = warnings_by_file_child[file_path]
            
            # 每文件对只读取一次文件内容
            parent_content = self.get_file_content(
                pa_group[0]['project_name_with_version'], file_path
            )
            child_content = self.get_file_content(
                ca_group[0]['project_name_with_version'], file_path
            )

            # 每文件对只计算一次 diff（供位置匹配复用）
            diff_matches: List[Tuple[int, int]] = []
            if parent_content and child_content:
                diff_matches = self._get_diff_matches(
                    parent_content.split('\n'), child_content.split('\n')
                )

            # 每文件对只计算一次 child snippet/hash（供后续匹配复用）
            child_snippets: Dict[int, Optional[str]] = {}
            child_hashes_first: Dict[int, str] = {}
            child_hashes_last: Dict[int, str] = {}
            if parent_content and child_content:
                for ca in ca_group:
                    ln = ca.get('line_number', 0)
                    child_snippets[ln] = self.get_code_snippet(child_content, ln)
                    child_line_text = self.get_code_line(child_content, ln) or ''
                    child_hashes_first[ln] = self._hash_first_tokens(child_line_text)
                    child_hashes_last[ln] = self._hash_last_tokens(child_line_text)

            # 遍历文件中的每个父告警
            for pa in pa_group:
                matched_child = None
                match_type = None

                # 过滤出尚未被匹配的子告警
                available_ca = [c for c in ca_group if c['id'] not in child_matched_ids]
                if not available_ca:
                    unmatched_parent.append(pa)
                    continue

                # 1. 精确匹配
                pa_line = pa.get('line_number', 0)
                for ca in available_ca:
                    if self.exact_matching(pa, ca):
                        matched_child = ca
                        match_type = 'exact'
                        break

                # 2. 位置匹配（复用预计算 diff）
                if not matched_child and diff_matches:
                    for ca in available_ca:
                        if self.location_based_matching_with_diff(pa, ca, diff_matches):
                            matched_child = ca
                            match_type = 'location'
                            break

                # 3. 片段匹配（复用预计算 parent snippet）
                if not matched_child and parent_content and child_content:
                    parent_snippet = self.get_code_snippet(parent_content, pa_line)
                    if parent_snippet:
                        for ca in available_ca:
                            ca_snippet = child_snippets.get(ca.get('line_number', 0))
                            if ca_snippet:
                                sim = self.calculate_similarity(parent_snippet, ca_snippet)
                                if sim >= self.SNIPPET_SIMILARITY:
                                    matched_child = ca
                                    match_type = 'snippet'
                                    break

                # 4. 哈希匹配（复用预计算 child hashes）
                if not matched_child and parent_content and child_content:
                    parent_line_text = self.get_code_line(parent_content, pa_line) or ''
                    pa_first = self._hash_first_tokens(parent_line_text)
                    pa_last = self._hash_last_tokens(parent_line_text)
                    if pa_first or pa_last:
                        for ca in available_ca:
                            ca_ln = ca.get('line_number', 0)
                            if (pa_first and pa_first == child_hashes_first.get(ca_ln)) or \
                               (pa_last and pa_last == child_hashes_last.get(ca_ln)):
                                matched_child = ca
                                match_type = 'hash'
                                break

                if matched_child:
                    child_matched_ids.add(matched_child['id'])
                    matched_pairs.append({
                        'parent': pa,
                        'child': matched_child,
                        'type': match_type
                    })
                    self.match_stats[match_type] += 1
                else:
                    unmatched_parent.append(pa)

        return {
            'matched_pairs': matched_pairs,
            'unmatched_parent': unmatched_parent
        }
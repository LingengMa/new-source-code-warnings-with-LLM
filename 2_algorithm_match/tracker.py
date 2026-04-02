import json
import os
import uuid
from collections import defaultdict
from packaging.version import parse as parse_version
from match import Matcher

class LifecycleTracker:
    """
    负责追踪告警生命周期，并根据匹配结果标注其状态 (TP/FP/Unknown)。
    """
    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file
        self.matcher = Matcher()
        self.all_warnings = self._load_warnings()
        self.warnings_by_project = self._group_and_sort_warnings()

    def _load_warnings(self) -> list:
        """从 JSON 文件加载告警数据，并为每条告警分配唯一 ID。"""
        print(f"正在从 {self.input_file} 加载告警数据...")
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 为每条告警分配唯一 UUID（如果尚无 id 字段）
                for warning in data:
                    if 'id' not in warning:
                        warning['id'] = str(uuid.uuid4())
                print(f"成功加载 {len(data)} 条告警。")
                return data
        except FileNotFoundError:
            print(f"错误: 输入文件未找到 {self.input_file}")
            return []
        except json.JSONDecodeError:
            print(f"错误: 无法解析JSON文件 {self.input_file}")
            return []

    def _group_and_sort_warnings(self) -> defaultdict:
        """按项目分组并按版本排序告警。"""
        warnings_by_project = defaultdict(lambda: defaultdict(list))
        for warning in self.all_warnings:
            warnings_by_project[warning['project_name']][warning['project_version']].append(warning)

        # 对每个项目中的版本进行排序
        sorted_projects = defaultdict(dict)
        for project, versions in warnings_by_project.items():
            sorted_version_keys = sorted(versions.keys(), key=parse_version)
            sorted_versions = {key: versions[key] for key in sorted_version_keys}
            sorted_projects[project] = sorted_versions
            
        return sorted_projects

    def run(self):
        """执行告警生命周期追踪和标注。"""
        if not self.all_warnings:
            print("没有告警数据可处理。")
            return

        labeled_warnings = []
        processed_warnings = set()

        for project, versions in self.warnings_by_project.items():
            print(f"\n正在处理项目: {project}")
            sorted_versions = list(versions.keys())
            num_versions = len(sorted_versions)

            # 记录每条告警的最终标签
            labels = {}

            for i in range(num_versions):
                current_version = sorted_versions[i]
                current_warnings = versions[current_version]
                print(f"  - 版本 {current_version} ({len(current_warnings)} 条告警)")

                # 最新版本：所有告警标记为 Unknown
                if i == num_versions - 1:
                    for warning in current_warnings:
                        if warning['id'] not in processed_warnings:
                            labels[warning['id']] = 'Unknown'
                            processed_warnings.add(warning['id'])
                    continue

                # 本版本中尚未处理过的告警
                unprocessed = [w for w in current_warnings if w['id'] not in processed_warnings]

                # 批量比对：与每个后续版本做一次整体匹配
                for j in range(i + 1, num_versions):
                    if not unprocessed:
                        break
                    next_version = sorted_versions[j]
                    next_warnings = versions[next_version]

                    # 一次调用匹配所有 unprocessed 告警，文件只读一次
                    match_result = self.matcher.match_warnings_between_versions(
                        unprocessed, next_warnings
                    )

                    # 已匹配到的告警标记为 FP，不再检查后续版本
                    matched_parent_ids = {pair['parent']['id'] for pair in match_result['matched_pairs']}
                    for wid in matched_parent_ids:
                        labels[wid] = 'FP'

                    # 未匹配的继续与更后面的版本比较
                    unprocessed = [w for w in unprocessed if w['id'] not in matched_parent_ids]

                # 仍未匹配到的告警标记为 TP
                for w in unprocessed:
                    labels[w['id']] = 'TP'

                for w in current_warnings:
                    processed_warnings.add(w['id'])

            # 将标签写回告警对象
            for project_versions in versions.values():
                for warning in project_versions:
                    if warning['id'] in labels:
                        warning['label'] = labels[warning['id']]
                        labeled_warnings.append(warning)

        self.save_results(labeled_warnings)

    def save_results(self, labeled_warnings: list):
        """将标注好的结果保存到输出文件。"""
        # 确保输出目录存在
        output_dir = os.path.dirname(self.output_file)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        print(f"\n正在将 {len(labeled_warnings)} 条已标注的告警保存到 {self.output_file}...")
        
        # 为了保持与输入数据一致的顺序，我们创建一个ID到标签的映射
        label_map = {w['id']: w['label'] for w in labeled_warnings}
        
        final_output = []
        for original_warning in self.all_warnings:
            if original_warning['id'] in label_map:
                new_warning = original_warning.copy()
                new_warning['label'] = label_map[original_warning['id']]
                new_warning.pop('id', None)  # 移除内部使用的临时 id 字段
                final_output.append(new_warning)

        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(final_output, f, indent=4, ensure_ascii=False)
        
        print("保存成功。")
        self._print_stats(final_output)

    def _print_stats(self, final_output: list):
        """打印最终的统计信息。"""
        stats = defaultdict(int)
        for warning in final_output:
            stats[warning['label']] += 1
        
        total = len(final_output)
        print("\n--- 最终统计 ---")
        print(f"总告警数: {total}")
        for label, count in stats.items():
            percentage = (count / total) * 100 if total > 0 else 0
            print(f"  - {label}: {count} ({percentage:.2f}%)")
        print("------------------")


if __name__ == "__main__":
    # 确保我们从项目的根目录运行
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    input_json = os.path.join(base_dir, 'input', 'data_all.json')
    output_json = os.path.join(base_dir, 'output', 'data_all_labeled.json')

    tracker = LifecycleTracker(input_file=input_json, output_file=output_json)
    tracker.run()

"""
analyze.py — 读取 output/data_all.json，统计每个工具、每个版本、每个 CWE 的数据情况，
             分析结果导出为 output/analysis.md

运行方式：conda run -n extractor python analyze.py
"""

import json
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path(__file__).parent
INPUT_FILE = BASE_DIR / "output" / "data_all.json"
OUTPUT_FILE = BASE_DIR / "output" / "analysis.md"

TOOLS = ["codeql", "cppcheck", "csa", "semgrep"]


def load_data() -> list[dict]:
    with open(INPUT_FILE, encoding="utf-8") as f:
        return json.load(f)


def build_stats(data: list[dict]) -> dict:
    """构建多维统计结构"""
    # 每个工具的总数
    by_tool: dict[str, int] = defaultdict(int)
    # 每个工具×项目×版本的数量
    by_tool_project_version: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # 每个 CWE（工具维度下）
    by_cwe: dict[str, int] = defaultdict(int)
    by_tool_cwe: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # 有无 CWE
    with_cwe = 0
    without_cwe = 0
    # 每个项目的总数
    by_project: dict[str, int] = defaultdict(int)

    for w in data:
        tool = w["tool_name"]
        p_w_v = w["project_name_with_version"]
        cwes = w.get("cwe", [])

        by_tool[tool] += 1
        by_tool_project_version[tool][p_w_v] += 1
        by_project[w["project_name"]] += 1

        if cwes:
            with_cwe += 1
            for cwe in cwes:
                by_cwe[cwe] += 1
                by_tool_cwe[tool][cwe] += 1
        else:
            without_cwe += 1

    return {
        "total": len(data),
        "by_tool": dict(by_tool),
        "by_tool_project_version": {t: dict(v) for t, v in by_tool_project_version.items()},
        "by_cwe": dict(by_cwe),
        "by_tool_cwe": {t: dict(v) for t, v in by_tool_cwe.items()},
        "by_project": dict(by_project),
        "with_cwe": with_cwe,
        "without_cwe": without_cwe,
    }


def fmt_table(headers: list[str], rows: list[list]) -> str:
    """生成 Markdown 表格"""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))

    def fmt_row(cells):
        return "| " + " | ".join(str(c).ljust(col_widths[i]) for i, c in enumerate(cells)) + " |"

    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    lines = [fmt_row(headers), sep] + [fmt_row(r) for r in rows]
    return "\n".join(lines)


def generate_report(stats: dict) -> str:
    lines = []

    lines.append("# 警告数据分析报告\n")
    lines.append(f"**总警告数**：{stats['total']:,}\n")
    lines.append(
        f"**含 CWE**：{stats['with_cwe']:,}（{stats['with_cwe']/stats['total']*100:.1f}%）  "
        f"**不含 CWE**：{stats['without_cwe']:,}（{stats['without_cwe']/stats['total']*100:.1f}%）\n"
    )

    # ---- 按工具 ----
    lines.append("## 1. 各工具警告数量\n")
    tool_rows = sorted(stats["by_tool"].items(), key=lambda x: -x[1])
    rows = [[t, f"{n:,}", f"{n/stats['total']*100:.1f}%"] for t, n in tool_rows]
    lines.append(fmt_table(["工具", "警告数", "占比"], rows))
    lines.append("")

    # ---- 按项目 ----
    lines.append("## 2. 各项目警告数量\n")
    proj_rows = sorted(stats["by_project"].items(), key=lambda x: x[0])
    rows = [[p, f"{n:,}", f"{n/stats['total']*100:.1f}%"] for p, n in proj_rows]
    lines.append(fmt_table(["项目", "警告数", "占比"], rows))
    lines.append("")

    # ---- 按工具×版本 ----
    lines.append("## 3. 各工具×项目版本警告数量\n")
    for tool in TOOLS:
        if tool not in stats["by_tool_project_version"]:
            continue
        lines.append(f"### {tool}\n")
        version_data = sorted(stats["by_tool_project_version"][tool].items())
        rows = [[p_w_v, f"{n:,}"] for p_w_v, n in version_data]
        lines.append(fmt_table(["项目版本", "警告数"], rows))
        lines.append("")

    # ---- 按 CWE ----
    lines.append("## 4. 各 CWE 警告数量（全部工具合计）\n")
    if stats["by_cwe"]:
        cwe_rows = sorted(stats["by_cwe"].items(), key=lambda x: -x[1])
        rows = [[cwe, f"{n:,}", f"{n/stats['with_cwe']*100:.1f}%"] for cwe, n in cwe_rows]
        lines.append(fmt_table(["CWE", "警告数", "占含CWE警告比例"], rows))
    else:
        lines.append("_无 CWE 数据_")
    lines.append("")

    # ---- 按工具×CWE ----
    lines.append("## 5. 各工具的 CWE 分布\n")
    for tool in TOOLS:
        tool_cwe = stats["by_tool_cwe"].get(tool, {})
        if not tool_cwe:
            lines.append(f"### {tool}\n\n_无 CWE 标注_\n")
            continue
        lines.append(f"### {tool}\n")
        cwe_rows = sorted(tool_cwe.items(), key=lambda x: -x[1])
        total_tool = stats["by_tool"].get(tool, 1)
        rows = [[cwe, f"{n:,}", f"{n/total_tool*100:.1f}%"] for cwe, n in cwe_rows]
        lines.append(fmt_table(["CWE", "警告数", "占该工具警告比例"], rows))
        lines.append("")

    return "\n".join(lines)


def main():
    print(f"读取 {INPUT_FILE} ...")
    data = load_data()
    print(f"共 {len(data):,} 条记录，开始统计...\n")

    stats = build_stats(data)

    report = generate_report(stats)
    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"分析完成，报告写入 {OUTPUT_FILE}")
    print(f"\n摘要：")
    print(f"  总警告数：{stats['total']:,}")
    for tool, n in sorted(stats["by_tool"].items(), key=lambda x: -x[1]):
        print(f"  {tool:10s}: {n:>8,} 条")
    print(f"  含 CWE：{stats['with_cwe']:,}，无 CWE：{stats['without_cwe']:,}")


if __name__ == "__main__":
    main()

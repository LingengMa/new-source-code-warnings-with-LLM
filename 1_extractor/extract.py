"""
extract.py — 从四个静态分析工具的原始输出中提取警告，统一格式写入 output/data_all.json

支持工具：CodeQL (SARIF)、Cppcheck (XML)、CSA (HTML)、Semgrep (JSON)
运行方式：conda run -n extractor python extract.py
"""

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input" / "data"
REPO_DIR = BASE_DIR / "input" / "repository"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_FILE = OUTPUT_DIR / "data_all.json"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def resolve_project_name_with_version(project_name: str, project_version: str) -> str:
    """
    通过查找 input/repository/ 中的实际目录名来确定 project_name_with_version。
    匹配策略（按优先级）：
      1. <project>-<version>（点格式，如 ffmpeg-7.1.1）
      2. <project>-<version_underscore>（下划线格式，如 curl-8_7_1）
      3. 扫描所有以 <project>- 开头的目录，找版本号匹配的（处理 openssl-openssl-3.x.x 等特殊情况）
    若均未找到，默认返回点格式。
    """
    dot_ver = project_version
    under_ver = project_version.replace(".", "_")

    candidates = [
        f"{project_name}-{dot_ver}",
        f"{project_name}-{under_ver}",
    ]
    for name in candidates:
        if (REPO_DIR / name).is_dir():
            return name

    # 扫描匹配：目录以 project_name- 开头且以版本号结尾（支持中间有额外段，如 openssl-openssl-3.2.1）
    if REPO_DIR.is_dir():
        prefix = f"{project_name}-"
        for entry in REPO_DIR.iterdir():
            if not entry.is_dir():
                continue
            name = entry.name
            if name.lower().startswith(prefix) and (
                name.endswith(f"-{dot_ver}") or name.endswith(f"-{under_ver}")
            ):
                return name

    return f"{project_name}-{dot_ver}"


def parse_project_version_from_name(name: str, tool: str) -> tuple[str, str]:
    """
    从文件名或目录名推导 (project_name, project_version)。
    支持格式：
      curl-8.7.1_codeql.sarif  → curl, 8.7.1
      curl-8.7.1.xml           → curl, 8.7.1
      curl-8.7.1_semgrep.json  → curl, 8.7.1
      curl-8.7.1               → curl, 8.7.1  (CSA 目录名)
    """
    # 去除工具后缀
    stem = name
    for suffix in (f"_{tool}.sarif", f"_{tool}.json", ".xml", ".sarif", ".json"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break

    # 匹配 <project>-<version>，版本以数字开头（也支持 FFmpeg-n6.0 形式）
    m = re.match(r"^(.+?)-n?(\d[\d._-]*)$", stem, re.IGNORECASE)
    if not m:
        raise ValueError(f"无法从名称解析项目和版本: {name!r}")
    project = m.group(1).lower()
    version = m.group(2)
    return project, version


def normalize_file_path(raw_path: str, project_name: str) -> str:
    """
    将绝对路径转换为相对于项目根的路径。
    项目根目录形如 <project>-<version> 或 <project>-<project>-<version>（含数字的段）。
    如 /mnt/c/.../curl/curl-curl-8_7_1/src/foo.c → src/foo.c
    """
    parts = Path(raw_path).parts
    # 优先找含有版本号（数字）的项目目录段，如 curl-curl-8_7_1
    for i, part in enumerate(parts):
        if (
            part.lower().startswith(project_name.lower() + "-")
            and any(c.isdigit() for c in part)
        ):
            return str(Path(*parts[i + 1:])) if i + 1 < len(parts) else raw_path
    # 回退：找到与项目名完全相同的目录段（不太可能到这里）
    for i, part in enumerate(parts):
        if part.lower() == project_name.lower():
            return str(Path(*parts[i + 1:])) if i + 1 < len(parts) else raw_path
    return raw_path


# ---------------------------------------------------------------------------
# CodeQL (SARIF)
# ---------------------------------------------------------------------------

def extract_codeql(sarif_path: Path, project_name: str, project_version: str) -> list[dict]:
    with open(sarif_path, encoding="utf-8") as f:
        data = json.load(f)

    project_name_with_version = resolve_project_name_with_version(project_name, project_version)
    run = data["runs"][0]
    rules = {r["id"]: r for r in run["tool"]["driver"].get("rules", [])}
    warnings = []

    for result in run.get("results", []):
        rule_id = result.get("ruleId", "")
        rule = rules.get(rule_id, {})

        # CWE from rule tags like "external/cwe/cwe-401"
        tags = rule.get("properties", {}).get("tags", [])
        cwe_list = []
        for tag in tags:
            m = re.match(r"external/cwe/cwe-(\d+)", tag, re.IGNORECASE)
            if m:
                cwe_list.append(f"CWE-{m.group(1)}")

        severity = rule.get("defaultConfiguration", {}).get("level", "note").upper()

        locs = result.get("locations", [])
        if not locs:
            continue
        phys = locs[0].get("physicalLocation", {})
        file_path = phys.get("artifactLocation", {}).get("uri", "")
        line_number = phys.get("region", {}).get("startLine", 0)
        message = result.get("message", {}).get("text", "")

        warnings.append({
            "tool_name": "codeql",
            "project_name": project_name,
            "project_name_with_version": project_name_with_version,
            "project_version": project_version,
            "file_path": file_path,
            "line_number": line_number,
            "cwe": cwe_list,
            "rule_id": rule_id,
            "message": message,
            "severity": severity,
        })

    return warnings


# ---------------------------------------------------------------------------
# Cppcheck (XML)
# ---------------------------------------------------------------------------

def extract_cppcheck(xml_path: Path, project_name: str, project_version: str) -> list[dict]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    errors_elem = root.find("errors")
    if errors_elem is None:
        return []

    project_name_with_version = resolve_project_name_with_version(project_name, project_version)
    warnings = []

    for error in errors_elem:
        rule_id = error.get("id", "")
        message = error.get("msg", "")
        severity = error.get("severity", "").upper()
        cwe_raw = error.get("cwe", "")
        cwe_list = [f"CWE-{cwe_raw}"] if cwe_raw else []

        loc = error.find("location")
        if loc is None:
            continue
        raw_path = loc.get("file", "")
        line_number = int(loc.get("line", 0))
        file_path = normalize_file_path(raw_path, project_name)

        warnings.append({
            "tool_name": "cppcheck",
            "project_name": project_name,
            "project_name_with_version": project_name_with_version,
            "project_version": project_version,
            "file_path": file_path,
            "line_number": line_number,
            "cwe": cwe_list,
            "rule_id": rule_id,
            "message": message,
            "severity": severity,
        })

    return warnings


# ---------------------------------------------------------------------------
# CSA / Clang Static Analyzer (HTML)
# ---------------------------------------------------------------------------

def extract_csa(index_html: Path, project_name: str, project_version: str) -> list[dict]:
    with open(index_html, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "lxml")

    project_name_with_version = resolve_project_name_with_version(project_name, project_version)
    warnings = []

    # 报告表格中每行 class 以 bt_ 开头
    for row in soup.find_all("tr", class_=re.compile(r"^bt_")):
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        bug_group = cells[0].get_text(strip=True)
        bug_type = cells[1].get_text(strip=True)
        file_name = cells[2].get_text(strip=True)
        line_number_text = cells[4].get_text(strip=True)
        try:
            line_number = int(line_number_text)
        except ValueError:
            line_number = 0

        warnings.append({
            "tool_name": "csa",
            "project_name": project_name,
            "project_name_with_version": project_name_with_version,
            "project_version": project_version,
            "file_path": file_name,
            "line_number": line_number,
            "cwe": [],
            "rule_id": bug_type,
            "message": f"{bug_group}: {bug_type}",
            "severity": "WARNING",
        })

    return warnings


# ---------------------------------------------------------------------------
# Semgrep (JSON)
# ---------------------------------------------------------------------------

def extract_semgrep(json_path: Path, project_name: str, project_version: str) -> list[dict]:
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    project_name_with_version = resolve_project_name_with_version(project_name, project_version)
    warnings = []

    for result in data.get("results", []):
        rule_id = result.get("check_id", "")
        raw_path = result.get("path", "")
        file_path = normalize_file_path(raw_path, project_name)
        line_number = result.get("start", {}).get("line", 0)
        extra = result.get("extra", {})
        message = extra.get("message", "")
        severity = extra.get("severity", "WARNING").upper()

        # CWE 格式："CWE-676: Use of Potentially Dangerous Function" → "CWE-676"
        raw_cwes = extra.get("metadata", {}).get("cwe", [])
        cwe_list = []
        for cwe_str in raw_cwes:
            m = re.match(r"(CWE-\d+)", cwe_str)
            if m:
                cwe_list.append(m.group(1))

        warnings.append({
            "tool_name": "semgrep",
            "project_name": project_name,
            "project_name_with_version": project_name_with_version,
            "project_version": project_version,
            "file_path": file_path,
            "line_number": line_number,
            "cwe": cwe_list,
            "rule_id": rule_id,
            "message": message,
            "severity": severity,
        })

    return warnings


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def extract_all() -> list[dict]:
    all_warnings: list[dict] = []

    # --- CodeQL ---
    codeql_dir = INPUT_DIR / "codeql"
    for project_dir in sorted(codeql_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        for sarif_file in sorted(project_dir.glob("*.sarif")):
            try:
                project, version = parse_project_version_from_name(sarif_file.name, "codeql")
                warnings = extract_codeql(sarif_file, project, version)
                all_warnings.extend(warnings)
                print(f"[CodeQL]   {sarif_file.name}: {len(warnings)} 条")
            except Exception as e:
                print(f"[CodeQL]   错误 {sarif_file}: {e}")

    # --- Cppcheck ---
    cppcheck_dir = INPUT_DIR / "cppcheck"
    for project_dir in sorted(cppcheck_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        for xml_file in sorted(project_dir.glob("*.xml")):
            try:
                project, version = parse_project_version_from_name(xml_file.name, "cppcheck")
                warnings = extract_cppcheck(xml_file, project, version)
                all_warnings.extend(warnings)
                print(f"[Cppcheck] {xml_file.name}: {len(warnings)} 条")
            except Exception as e:
                print(f"[Cppcheck] 错误 {xml_file}: {e}")

    # --- CSA ---
    csa_dir = INPUT_DIR / "csa"
    for project_dir in sorted(csa_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        for version_dir in sorted(project_dir.iterdir()):
            if not version_dir.is_dir():
                continue
            index_html = version_dir / "index.html"
            if not index_html.exists():
                # 空目录：该工具该版本无警告
                continue
            try:
                project, version = parse_project_version_from_name(version_dir.name, "csa")
                warnings = extract_csa(index_html, project, version)
                all_warnings.extend(warnings)
                print(f"[CSA]      {version_dir.name}: {len(warnings)} 条")
            except Exception as e:
                print(f"[CSA]      错误 {version_dir}: {e}")

    # --- Semgrep ---
    semgrep_dir = INPUT_DIR / "semgrep"
    for project_dir in sorted(semgrep_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        for json_file in sorted(project_dir.glob("*.json")):
            try:
                project, version = parse_project_version_from_name(json_file.name, "semgrep")
                warnings = extract_semgrep(json_file, project, version)
                all_warnings.extend(warnings)
                print(f"[Semgrep]  {json_file.name}: {len(warnings)} 条")
            except Exception as e:
                print(f"[Semgrep]  错误 {json_file}: {e}")

    return all_warnings


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    print("开始提取警告...\n")
    warnings = extract_all()
    print(f"\n共提取 {len(warnings)} 条警告，写入 {OUTPUT_FILE}")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(warnings, f, ensure_ascii=False, indent=2)
    print("完成。")


if __name__ == "__main__":
    main()

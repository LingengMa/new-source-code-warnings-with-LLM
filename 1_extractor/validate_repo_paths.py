"""
validate_repo_paths.py — 验证 data_all.json 中所有 project_name_with_version
能否在 input/repository/ 中找到对应目录

运行方式：conda run -n extractor python validate_repo_paths.py
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
REPO_DIR = BASE_DIR / "input" / "repository"
DATA_FILE = BASE_DIR / "output" / "data_all.json"


def main():
    with open(DATA_FILE, encoding="utf-8") as f:
        warnings = json.load(f)

    # 收集所有唯一的 project_name_with_version
    all_keys: set[str] = {w["project_name_with_version"] for w in warnings}

    missing: list[str] = []
    found: list[str] = []

    for key in sorted(all_keys):
        if (REPO_DIR / key).is_dir():
            found.append(key)
        else:
            missing.append(key)

    print(f"共 {len(all_keys)} 个唯一 project_name_with_version\n")

    if found:
        print(f"✅ 找到 ({len(found)}):")
        for k in found:
            print(f"   {k}")

    if missing:
        print(f"\n❌ 缺失 ({len(missing)}):")
        for k in missing:
            print(f"   {k}")
    else:
        print("\n✅ 全部匹配，无缺失。")

    return len(missing)


if __name__ == "__main__":
    exit(main())

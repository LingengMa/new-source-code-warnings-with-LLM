"""
Stage 4_2: Warning Data Filtering

Applies four sequential filters to data_remaining_cwe_supplement.json:
  1. CWE top25: keep only entries whose cwe list intersects the top-25 set
  2. Test files: drop entries from test/fuzz/benchmark source files
  3. #define lines: drop entries whose target source line is a #define
  4. Last version: drop entries from the latest version of each project

Run: conda run -n data_filter python filter.py
Output:
  output/data_filtered.json
  output/filter_stats.json
  output/analysis.json
  output/analysis.md
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from packaging.version import Version

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
OUTPUT_DIR = BASE_DIR / "output"
REPO_DIR = INPUT_DIR / "repository"

TOP25_FILE = INPUT_DIR / "cwe-top25"
DATA_FILE = INPUT_DIR / "data_remaining_cwe_supplement.json"

OUTPUT_DATA = OUTPUT_DIR / "data_filtered.json"
OUTPUT_STATS = OUTPUT_DIR / "filter_stats.json"
OUTPUT_ANALYSIS = OUTPUT_DIR / "analysis.json"
OUTPUT_ANALYSIS_MD = OUTPUT_DIR / "analysis.md"


# ---------------------------------------------------------------------------
# Step 1: CWE top25 filter
# ---------------------------------------------------------------------------

def parse_top25(path: Path) -> set[str]:
    """Extract all CWE-NNN tokens from the top25 file."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"CWE-\d+", text))


def filter_cwe_top25(data: list[dict], top25: set[str]) -> list[dict]:
    return [e for e in data if set(e.get("cwe", [])) & top25]


# ---------------------------------------------------------------------------
# Step 2: Test file filter
# ---------------------------------------------------------------------------

# Directory components (full path segment, case-insensitive) that mark a file
# as belonging to a test/fuzz/benchmark tree.
_TEST_DIR_SEGMENTS = frozenset(
    ["test", "tests", "fuzz", "fuzzing", "oss-fuzz", "benchmark", "benchmarks", "testdir", "spec"]
)

# Exact filenames that are test infrastructure files.
_TEST_EXACT_FILENAMES = frozenset(["conftest.c", "test.c"])

# Filename substrings that indicate a test file (matched on the basename).
_TEST_FILENAME_PATTERNS = re.compile(
    r"neontest|_fuzzer\.|_fuzz\.|_bench\.",
    re.IGNORECASE,
)


def is_test_file(file_path: str) -> bool:
    """
    Return True if file_path is a test/fuzz/benchmark file.

    Uses directory-component matching to avoid false positives like
    musl's pthread_testcancel.c (a real POSIX API, not a test).
    """
    parts = Path(file_path).parts
    # Check parent directory components (exclude the filename itself)
    for segment in parts[:-1]:
        if segment.lower() in _TEST_DIR_SEGMENTS:
            return True

    filename = parts[-1].lower() if parts else ""
    if filename in _TEST_EXACT_FILENAMES:
        return True
    if _TEST_FILENAME_PATTERNS.search(filename):
        return True

    return False


def filter_test_files(data: list[dict]) -> list[dict]:
    return [e for e in data if not is_test_file(e["file_path"])]


# ---------------------------------------------------------------------------
# Step 3: #define line filter
# ---------------------------------------------------------------------------

def _read_file_lines(path: Path) -> list[str] | None:
    """Read all lines from a file, returning None if the file doesn't exist."""
    if not path.exists():
        return None
    try:
        return path.read_text(errors="ignore").splitlines()
    except OSError:
        return None


def is_define_line(entry: dict, file_cache: dict) -> bool:
    """
    Return True if the warning's target line is a #define.
    Missing files are treated as non-define (entry is kept).
    """
    key = (entry["project_name_with_version"], entry["file_path"])
    if key not in file_cache:
        file_cache[key] = _read_file_lines(REPO_DIR / entry["project_name_with_version"] / entry["file_path"])

    lines = file_cache[key]
    if lines is None:
        return False  # file not found — keep entry

    line_idx = entry["line_number"] - 1
    if not (0 <= line_idx < len(lines)):
        return False  # line out of range — keep entry

    return lines[line_idx].lstrip().startswith("#define")


def filter_define_lines(data: list[dict]) -> tuple[list[dict], int]:
    file_cache: dict = {}
    missing = 0
    kept = []
    for e in data:
        key = (e["project_name_with_version"], e["file_path"])
        if key not in file_cache:
            file_cache[key] = _read_file_lines(
                REPO_DIR / e["project_name_with_version"] / e["file_path"]
            )
            if file_cache[key] is None:
                missing += 1
        if not is_define_line(e, file_cache):
            kept.append(e)
    return kept, missing


# ---------------------------------------------------------------------------
# Step 4: Last version filter
# ---------------------------------------------------------------------------

def find_last_versions(data: list[dict]) -> dict[str, str]:
    """Return {project_name: latest_project_version_string}."""
    versions_by_project: dict[str, set[str]] = defaultdict(set)
    for e in data:
        versions_by_project[e["project_name"]].add(e["project_version"])

    last: dict[str, str] = {}
    for project, versions in versions_by_project.items():
        last[project] = max(versions, key=Version)
    return last


def filter_last_version(data: list[dict]) -> tuple[list[dict], dict[str, str]]:
    last = find_last_versions(data)
    kept = [e for e in data if e["project_version"] != last[e["project_name"]]]
    return kept, last


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def build_analysis(data: list[dict]) -> dict:
    by_cwe: Counter = Counter()
    by_project: Counter = Counter()
    by_tool: Counter = Counter()
    by_label: Counter = Counter()

    for e in data:
        for cwe in e.get("cwe", []):
            by_cwe[cwe] += 1
        by_project[e["project_name"]] += 1
        by_tool[e["tool_name"]] += 1
        by_label[e.get("label", "Unknown")] += 1

    return {
        "total": len(data),
        "by_cwe": dict(by_cwe.most_common()),
        "by_project": dict(by_project.most_common()),
        "by_tool": dict(by_tool.most_common()),
        "by_label": dict(by_label.most_common()),
    }


def _table(title: str, counts: dict[str, int]) -> str:
    lines = [f"### {title}", "", "| Name | Count |", "|------|-------|"]
    for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {name} | {cnt} |")
    return "\n".join(lines)


def build_analysis_md(analysis: dict, stats: dict) -> str:
    sections = [
        "# Stage 4_2 Filter Analysis",
        "",
        "## Filter Steps",
        "",
        "| Step | Before | After | Dropped |",
        "|------|--------|-------|---------|",
    ]
    for step, s in stats.items():
        sections.append(f"| {step} | {s['before']} | {s['after']} | {s['dropped']} |")

    sections += [
        "",
        f"## Final Dataset: {analysis['total']} warnings",
        "",
        _table("By CWE", analysis["by_cwe"]),
        "",
        _table("By Project", analysis["by_project"]),
        "",
        _table("By Tool", analysis["by_tool"]),
        "",
        _table("By Label", analysis["by_label"]),
    ]
    return "\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Loading {DATA_FILE.name} ...", flush=True)
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)
    print(f"  Total input: {len(data)}")

    stats: dict[str, dict] = {}

    # Step 1 — CWE top25
    top25 = parse_top25(TOP25_FILE)
    print(f"  Top25 CWEs loaded: {sorted(top25)}", flush=True)
    before = len(data)
    data = filter_cwe_top25(data, top25)
    stats["1_cwe_top25"] = {"before": before, "after": len(data), "dropped": before - len(data)}
    print(f"Step 1 (CWE top25):    {before} → {len(data)}  (dropped {before - len(data)})", flush=True)

    # Step 2 — Test files
    before = len(data)
    data = filter_test_files(data)
    stats["2_test_files"] = {"before": before, "after": len(data), "dropped": before - len(data)}
    print(f"Step 2 (test files):   {before} → {len(data)}  (dropped {before - len(data)})", flush=True)

    # Step 3 — #define lines
    before = len(data)
    data, missing_files = filter_define_lines(data)
    stats["3_define_lines"] = {
        "before": before,
        "after": len(data),
        "dropped": before - len(data),
        "missing_files": missing_files,
    }
    print(f"Step 3 (#define):      {before} → {len(data)}  (dropped {before - len(data)}, missing files: {missing_files})", flush=True)

    # Step 4 — Last version
    before = len(data)
    data, last_versions = filter_last_version(data)
    stats["4_last_version"] = {
        "before": before,
        "after": len(data),
        "dropped": before - len(data),
        "last_versions": last_versions,
    }
    print(f"Step 4 (last version): {before} → {len(data)}  (dropped {before - len(data)})", flush=True)
    print(f"  Last versions dropped: {last_versions}")

    # Analysis
    analysis = build_analysis(data)
    analysis_md = build_analysis_md(analysis, stats)

    # Write outputs
    print(f"\nWriting {OUTPUT_DATA.name} ...", flush=True)
    with open(OUTPUT_DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_ANALYSIS, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    with open(OUTPUT_ANALYSIS_MD, "w", encoding="utf-8") as f:
        f.write(analysis_md)

    print(f"Done. Final dataset: {len(data)} warnings.")
    print(f"Output: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()

"""
Stage 4_1: CWE Information Supplement

Fills empty `cwe` fields in data_remaining.json by looking up rule_id
against tool-specific CWE mapping files in input/cwe_information/.

Mapping strategy per tool:
  - codeql:   ruleId → CWEs parsed from rule.properties.tags
  - cppcheck: id     → CWE integer field → "CWE-NNN"
  - csa:      Bug Type (== rule_id) → CWE-ID integer field → "CWE-NNN"
  - semgrep:  already complete, skipped

Run: conda run -n cwe_supplement python supplement.py
Output:
  output/data_cwe_supplemented.json
  output/supplement_stats.json
"""

import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
CWE_DIR = INPUT_DIR / "cwe_information"
OUTPUT_DIR = BASE_DIR / "output"

DATA_FILE = INPUT_DIR / "data_remaining.json"
OUTPUT_FILE = OUTPUT_DIR / "data_remaining_cwe_supplement.json"
STATS_FILE = OUTPUT_DIR / "supplement_stats.json"


# ---------------------------------------------------------------------------
# Mapping builders
# ---------------------------------------------------------------------------

def _int_to_cwe(n) -> str:
    """Convert integer 758 → 'CWE-758'."""
    return f"CWE-{int(n)}"


def build_codeql_mapping() -> dict[str, list[str]]:
    """
    Returns {ruleId: ["CWE-NNN", ...]} by parsing rule.properties.tags.
    Falls back to the integer cwe field when tags yield nothing.
    """
    path = CWE_DIR / "codeql" / "merged_codeql_C_report.json"
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)

    mapping: dict[str, list[str]] = {}
    for e in entries:
        rule_id = e.get("ruleId")
        if not rule_id:
            continue

        cwes: list[str] = []
        tags = e.get("rule.properties.tags") or ""
        # tags format: "security, external/cwe/cwe-260, external/cwe/cwe-313"
        for token in re.findall(r"external/cwe/cwe-(\d+)", tags, re.IGNORECASE):
            cwes.append(f"CWE-{token}")

        if not cwes and e.get("cwe") is not None:
            cwes = [_int_to_cwe(e["cwe"])]

        if cwes:
            mapping[rule_id] = cwes

    return mapping


def build_cppcheck_mapping() -> dict[str, list[str]]:
    """Returns {id: ["CWE-NNN"]} from the reference file plus all semantic assignments.

    Semantic assignments cover rules absent from the reference file; rules whose
    semantic analysis concluded no CWE is applicable (tool diagnostics, parse
    failures, missing headers) are intentionally omitted.
    """
    path = CWE_DIR / "merged_cppcheck_report.json"
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)

    mapping: dict[str, list[str]] = {}
    for e in entries:
        rule_id = e.get("id")
        cwe = e.get("cwe")
        if rule_id and cwe is not None:
            mapping[rule_id] = [_int_to_cwe(cwe)]

    # Semantic CWE assignments for rules not present in the reference file.
    # Rules that are pure tool diagnostics (no code defect) map to None and are skipped.
    # Derived from systematic analysis in analyze_cppcheck_rules.py::SEMANTIC_ANALYSIS.
    _SEMANTIC_ASSIGNMENTS: dict[str, str | None] = {
        "checkLevelNormal":        None,   # tool notification, no defect
        "internalAstError":        None,   # tool internal failure
        "internalError":           None,   # tool internal failure
        "missingInclude":          None,   # missing header, not a defect
        "missingIncludeSystem":    None,   # missing system header, not a defect
        "noValidConfiguration":    None,   # analysis could not run
        "preprocessorErrorDirective": None,  # build guards / preprocessing artifacts
        "returnImplicitInt":       "CWE-758",  # reliance on pre-C99 implicit-int (portability)
        "syntaxError":             None,   # preprocessor branch artifact, not a real syntax error
        "unknownMacro":            None,   # macro definition missing, no defect identified
    }
    for rule_id, cwe_str in _SEMANTIC_ASSIGNMENTS.items():
        if cwe_str is not None:
            mapping[rule_id] = [cwe_str]

    return mapping


def build_csa_mapping() -> dict[str, list[str]]:
    """Returns {Bug Type: ["CWE-NNN"]} from the CWE-ID integer field."""
    path = CWE_DIR / "csa_merged_cwe.json"
    with open(path, encoding="utf-8") as f:
        entries = json.load(f)

    mapping: dict[str, list[str]] = {}
    for e in entries:
        bug_type = e.get("Bug Type")
        cwe_id = e.get("CWE-ID")
        if bug_type and cwe_id is not None:
            mapping[bug_type] = [_int_to_cwe(cwe_id)]

    return mapping


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Loading data_remaining.json …")
    with open(DATA_FILE, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    print(f"  {len(data):,} entries loaded")

    print("Building CWE lookup tables …")
    mappings = {
        "codeql": build_codeql_mapping(),
        "cppcheck": build_cppcheck_mapping(),
        "csa": build_csa_mapping(),
    }
    for tool, m in mappings.items():
        print(f"  {tool}: {len(m)} rules mapped")

    # Stats counters  {tool: {supplemented, already_had, still_missing, total}}
    stats: dict[str, dict[str, int]] = {}

    print("Supplementing CWE fields …")
    for entry in data:
        tool = entry["tool_name"]
        if tool not in stats:
            stats[tool] = {"total": 0, "already_had_cwe": 0,
                           "supplemented": 0, "still_missing": 0}
        stats[tool]["total"] += 1

        if entry.get("cwe"):
            stats[tool]["already_had_cwe"] += 1
            continue  # already complete, never overwrite

        lookup = mappings.get(tool)
        if lookup is None:
            # semgrep — already complete
            stats[tool]["already_had_cwe"] += 1
            continue

        rule_id = entry.get("rule_id", "")
        cwes = lookup.get(rule_id)
        if cwes:
            entry["cwe"] = cwes
            stats[tool]["supplemented"] += 1
        else:
            stats[tool]["still_missing"] += 1

    # Summary to console
    total_supp = sum(s["supplemented"] for s in stats.values())
    total_miss = sum(s["still_missing"] for s in stats.values())
    print(f"\nResults:")
    print(f"  Supplemented: {total_supp:,}")
    print(f"  Still missing (no mapping): {total_miss:,}")
    for tool, s in sorted(stats.items()):
        print(f"  [{tool}] total={s['total']:,}  had={s['already_had_cwe']:,}  "
              f"supplemented={s['supplemented']:,}  missing={s['still_missing']:,}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nWriting {OUTPUT_FILE} …")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Writing {STATS_FILE} …")
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total_entries": len(data),
                "total_supplemented": total_supp,
                "total_still_missing": total_miss,
                "by_tool": stats,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print("Done.")


if __name__ == "__main__":
    main()

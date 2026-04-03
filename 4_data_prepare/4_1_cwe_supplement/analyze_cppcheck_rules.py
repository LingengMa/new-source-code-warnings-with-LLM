"""
analyze_cppcheck_rules.py

Systematically analyzes all unique cppcheck rule_ids found in data_remaining.json:
  - Checks each against merged_cppcheck_report.json (exact id match)
  - For unmatched rules, applies semantic analysis based on actual warning messages
    and the established severity→CWE patterns in the cppcheck reference:
      portability → CWE-758 / CWE-467 / CWE-704 / CWE-686 / CWE-475
      style/information → CWE-398
      (tool diagnostic messages → no CWE)
  - Records: entry count in data, CWE found, match type, reasoning

Output: output/cppcheck_rule_analysis.json
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
INPUT_DIR = BASE_DIR / "input"
CWE_DIR = INPUT_DIR / "cwe_information"
OUTPUT_DIR = BASE_DIR / "output"

DATA_FILE = INPUT_DIR / "data_remaining.json"
CPPCHECK_MAP_FILE = CWE_DIR / "merged_cppcheck_report.json"
OUTPUT_FILE = OUTPUT_DIR / "cppcheck_rule_analysis.json"

# Semantic CWE assignments for rules not in the reference mapping.
# Each entry: (cwe_str | None, reasoning)
# Reasoning documents the semantic analysis that led to the decision.
SEMANTIC_ANALYSIS: dict[str, tuple[str | None, str]] = {
    "checkLevelNormal": (
        None,
        "Severity=INFORMATION. Message: 'Limiting ValueFlow analysis since function is too "
        "complex.' Pure tool notification about analysis depth; no code defect is detected. "
        "No CWE applicable.",
    ),
    "internalAstError": (
        None,
        "Severity=ERROR. Message: 'AST broken, X doesn't have a parent/operand.' "
        "Cppcheck's internal AST failed to parse the code structure; this reflects a tool "
        "limitation, not a detectable code defect. No CWE applicable.",
    ),
    "internalError": (
        None,
        "Severity=ERROR. Messages: 'Cyclic reverse analysis', 'MathLib out_of_range'. "
        "Cppcheck crashed or hit an internal processing limit; no code defect is identified. "
        "No CWE applicable.",
    ),
    "missingInclude": (
        None,
        "Severity=INFORMATION. Message: 'Include file X not found.' "
        "Missing header dependency prevents full analysis but is not itself a security defect. "
        "No CWE applicable.",
    ),
    "missingIncludeSystem": (
        None,
        "Severity=INFORMATION. Message: 'Include file <X> not found.' "
        "Same as missingInclude for system headers. Cppcheck explicitly notes it does not need "
        "standard headers for correct results. No CWE applicable.",
    ),
    "noValidConfiguration": (
        None,
        "Severity=INFORMATION. Message: 'File not analyzed; cppcheck failed to extract a valid "
        "configuration.' Analysis could not run; no defect is reported. No CWE applicable.",
    ),
    "preprocessorErrorDirective": (
        None,
        "Severity=ERROR. Messages include intentional #error build guards "
        "('Not a standard compliant compiler', 'upgrade your libcurl') and macro expansion "
        "failures. These are build-time guards or preprocessing artifacts, not runtime security "
        "defects. No CWE applicable.",
    ),
    "returnImplicitInt": (
        "CWE-758",
        "Severity=PORTABILITY. Message: 'Omitted return type of function X defaults to int, "
        "not supported by ISO C99 and later standards.' "
        "Semantic match: reliance on pre-C99 implicit-int behavior that is implementation-defined "
        "or removed in C99+. This is semantically equivalent to other portability rules that use "
        "CWE-758 (e.g. AssignmentAddressToInteger, shiftTooManyBitsSigned, pointerOutOfBounds) — "
        "all are 'reliance on undefined/unspecified/implementation-defined behavior' (CWE-758). "
        "Severity=PORTABILITY also matches the CWE-758 cluster in the reference mapping.",
    ),
    "syntaxError": (
        None,
        "Severity=ERROR. Messages: 'Unmatched {. Configuration: X'. These arise when cppcheck "
        "evaluates preprocessor branches with specific macro configurations that the source is "
        "not designed for (conditional compilation artifacts). Not a real syntax error in the "
        "target build. No CWE applicable.",
    ),
    "unknownMacro": (
        None,
        "Severity=ERROR. Message: 'Unknown macro X, configuration required.' "
        "Cppcheck lacks the macro definition needed for analysis; it reports the location but "
        "cannot identify a specific defect. No CWE applicable.",
    ),
}


def main() -> None:
    print("Loading data_remaining.json …")
    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    print("Loading cppcheck CWE mapping …")
    with open(CPPCHECK_MAP_FILE, encoding="utf-8") as f:
        cpp_map_entries = json.load(f)

    # Build mapping: id → entry
    cpp_mapping: dict[str, dict] = {e["id"]: e for e in cpp_map_entries if "id" in e}

    # Count entries per rule_id from data, and existing CWE coverage
    rule_stats: dict[str, dict] = {}
    for entry in data:
        if entry["tool_name"] != "cppcheck":
            continue
        rid = entry["rule_id"]
        if rid not in rule_stats:
            rule_stats[rid] = {"total": 0, "already_has_cwe": 0, "no_cwe": 0}
        rule_stats[rid]["total"] += 1
        if entry.get("cwe"):
            rule_stats[rid]["already_has_cwe"] += 1
        else:
            rule_stats[rid]["no_cwe"] += 1

    # Build analysis records for all rule_ids
    analysis = []
    for rid in sorted(rule_stats):
        stats = rule_stats[rid]
        map_entry = cpp_mapping.get(rid)

        if map_entry is not None:
            cwe_int = map_entry.get("cwe")
            cwe_str = f"CWE-{int(cwe_int)}" if cwe_int is not None else None
            record = {
                "rule_id": rid,
                "status": "mapped",
                "match_type": "reference",
                "cwe": cwe_str,
                "entries_total": stats["total"],
                "entries_already_had_cwe": stats["already_has_cwe"],
                "entries_supplemented": stats["no_cwe"] if cwe_str else 0,
                "entries_still_missing": 0 if cwe_str else stats["no_cwe"],
                "reasoning": None,
            }
        elif rid in SEMANTIC_ANALYSIS:
            cwe_str, reasoning = SEMANTIC_ANALYSIS[rid]
            has_cwe = cwe_str is not None
            record = {
                "rule_id": rid,
                "status": "semantic_match" if has_cwe else "no_cwe_diagnostic",
                "match_type": "semantic" if has_cwe else None,
                "cwe": cwe_str,
                "entries_total": stats["total"],
                "entries_already_had_cwe": stats["already_has_cwe"],
                "entries_supplemented": stats["no_cwe"] if has_cwe else 0,
                "entries_still_missing": 0 if has_cwe else stats["no_cwe"],
                "reasoning": reasoning,
            }
        else:
            record = {
                "rule_id": rid,
                "status": "unknown",
                "match_type": None,
                "cwe": None,
                "entries_total": stats["total"],
                "entries_already_had_cwe": stats["already_has_cwe"],
                "entries_supplemented": 0,
                "entries_still_missing": stats["no_cwe"],
                "reasoning": "Not found in any cwe_information source; manual review required",
            }
        analysis.append(record)

    # Summary
    total_rules = len(analysis)
    by_status = {}
    for a in analysis:
        by_status[a["status"]] = by_status.get(a["status"], 0) + 1
    supplementable = sum(a["entries_supplemented"] for a in analysis)
    still_missing = sum(a["entries_still_missing"] for a in analysis)

    print(f"\nRule analysis summary:")
    print(f"  Total unique rule_ids: {total_rules}")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")
    print(f"  Entries supplementable (reference + semantic): {supplementable:,}")
    print(f"  Entries with no applicable CWE (diagnostic): {still_missing:,}")

    semantic = [a for a in analysis if a["status"] == "semantic_match"]
    if semantic:
        print(f"\n  Semantic CWE assignments:")
        for a in semantic:
            print(f"    {a['rule_id']} → {a['cwe']} ({a['entries_total']} entries)")

    unknown_rules = [a for a in analysis if a["status"] == "unknown"]
    if unknown_rules:
        print("\n  ⚠ Unknown rules (need manual review):")
        for a in unknown_rules:
            print(f"    {a['rule_id']}: {a['entries_total']} entries")

    output = {
        "summary": {
            "total_unique_rule_ids": total_rules,
            "by_status": by_status,
            "entries_supplementable": supplementable,
            "entries_no_applicable_cwe": still_missing,
        },
        "rules": analysis,
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nWritten: {OUTPUT_FILE}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nWritten: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

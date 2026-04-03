# Design: CWE Supplement Mapping Strategy

## Overview

`data_remaining.json` stores `cwe` as a list of strings (e.g. `["CWE-119", "CWE-120"]`).
Many entries have an empty list. This stage fills those gaps using rule-id-based
lookup tables built from `input/cwe_information/`.

CWE values are **never overwritten** — only entries with an empty `cwe` list are touched.

---

## Per-Tool Mapping

### CodeQL

**Source file:** `cwe_information/codeql/merged_codeql_C_report.json`

Each entry has a `ruleId` and a `rule.properties.tags` string like:
```
"security, external/cwe/cwe-260, external/cwe/cwe-313"
```

All tokens matching `external/cwe/cwe-NNN` are extracted and formatted as `"CWE-NNN"`.
This is consistent with how the original extractor (stage 1) populated existing CWEs
from CodeQL SARIF tags — some rules map to multiple CWEs.

Fallback: if tags yield nothing, the integer `cwe` field is used (`758` → `"CWE-758"`).

**Coverage:** 82 rules in mapping, all 34 rules with missing CWE in the data are covered → 0 remaining gaps.

### Cppcheck

**Source file:** `cwe_information/merged_cppcheck_report.json`

Each entry has an `id` field (the rule name) and an integer `cwe` field.
Mapping: `id` → `["CWE-NNN"]` (single value).

**Coverage — semantic analysis for unmatched rules:**

`analyze_cppcheck_rules.py` extracted all 137 unique cppcheck rule_ids from
`data_remaining.json`, checked each against `merged_cppcheck_report.json` and all other
`cwe_information` source files, then applied semantic analysis to the 10 unmatched rules
by examining their actual warning messages and comparing against the established
severity→CWE patterns in the reference (portability→CWE-758, style→CWE-398, etc.).

**Semantic match — `returnImplicitInt` → CWE-758 (204 entries):**

Severity=PORTABILITY. Message: *"Omitted return type of function X defaults to int,
not supported by ISO C99 and later standards."* This is semantically equivalent to other
portability rules that all map to CWE-758 (Reliance on Undefined/Implementation-Defined
Behavior): `AssignmentAddressToInteger`, `shiftTooManyBitsSigned`, `pointerOutOfBounds`, etc.
Implicit int is behavior removed in C99 — reliance on it is implementation-defined.

**9 diagnostic rule IDs with no applicable CWE:**

Searched across all `cwe_information` source files (no matches). Semantic analysis of
actual messages confirms these are tool-internal diagnostics, not code defects:

| rule_id | Severity | Semantic meaning | Reason no CWE |
|---------|----------|-----------------|---------------|
| `checkLevelNormal` | INFORMATION | "Limiting ValueFlow analysis since function is too complex" | Tool analysis depth notification; no defect detected |
| `internalAstError` | ERROR | "AST broken, X doesn't have a parent/operand" | Tool failed to parse AST; not a code defect |
| `internalError` | ERROR | "Cyclic reverse analysis" / "MathLib out_of_range" | Tool internal crash; no defect identified |
| `missingInclude` | INFORMATION | "Include file X not found" | Missing header for analysis; not a security issue |
| `missingIncludeSystem` | INFORMATION | "System header X not found" | Same as missingInclude for system headers |
| `noValidConfiguration` | INFORMATION | "File not analyzed; no valid configuration" | Analysis could not run; no defect reported |
| `preprocessorErrorDirective` | ERROR | "#error X" / "failed to expand macro Y" | Intentional build guards or macro expansion failures; not runtime defects |
| `syntaxError` | ERROR | "Unmatched '{'. Configuration: X" | Preprocessor branch artifact in non-target config; not a real syntax error |
| `unknownMacro` | ERROR | "Unknown macro X, configuration required" | Configuration limitation; no defect identified |

Full per-rule reasoning is in `output/cppcheck_rule_analysis.json` (field: `reasoning`).

### CSA (Clang Static Analyzer)

**Source file:** `cwe_information/csa_merged_cwe.json`

Each entry has a `Bug Type` field and an integer `CWE-ID` field.
The `rule_id` in `data_remaining.json` for CSA warnings equals the `Bug Type` exactly.
Mapping: `Bug Type` → `["CWE-NNN"]`.

**Coverage:** 24 entries in mapping, all 23 distinct CSA rule_ids in the data are covered → 0 remaining gaps.

### Semgrep

Already 100% complete in `data_remaining.json` — no supplement needed.

---

## CWE Format

All CWE values are stored as `"CWE-NNN"` strings (zero-padded to match standard
notation, e.g. `"CWE-22"` not `"CWE-022"`). The `cwe` field is always a list,
even when only one CWE applies: `["CWE-119"]`.

---

## Coverage Summary

| Tool | Rules with missing CWE | Reference-mapped | Semantic-matched | No CWE (diagnostic) |
|------|----------------------|-----------------|-----------------|---------------------|
| codeql | 34 | 34 (100%) | 0 | 0 |
| cppcheck | 15 | 5 | 1 (`returnImplicitInt`→CWE-758) | 9 |
| csa | 23 | 23 (100%) | 0 | 0 |
| semgrep | 0 | — | — | — |

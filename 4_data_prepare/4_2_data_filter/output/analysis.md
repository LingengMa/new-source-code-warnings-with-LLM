# Stage 4_2 Filter Analysis

## Filter Steps

| Step | Before | After | Dropped |
|------|--------|-------|---------|
| 1_cwe_top25 | 430496 | 3245 | 427251 |
| 2_test_files | 3245 | 3140 | 105 |
| 3_define_lines | 3140 | 3140 | 0 |
| 4_last_version | 3140 | 2386 | 754 |

## Final Dataset: 2386 warnings

### By CWE

| Name | Count |
|------|-------|
| CWE-476 | 2147 |
| CWE-20 | 155 |
| CWE-416 | 55 |
| CWE-502 | 18 |
| CWE-94 | 10 |
| CWE-78 | 1 |

### By Project

| Name | Count |
|------|-------|
| git | 723 |
| curl | 437 |
| vim | 385 |
| openssl | 238 |
| ffmpeg | 164 |
| tmux | 153 |
| nginx | 112 |
| redis | 86 |
| musl | 76 |
| libuv | 12 |

### By Tool

| Name | Count |
|------|-------|
| cppcheck | 1277 |
| csa | 925 |
| semgrep | 184 |

### By Label

| Name | Count |
|------|-------|
| FP | 2088 |
| TP | 298 |

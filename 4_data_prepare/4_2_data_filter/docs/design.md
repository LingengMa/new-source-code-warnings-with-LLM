# Design: Stage 4_2 Data Filter

## Filter 1: CWE Top-25

`input/cwe-top25` is a plain text file containing a ranking table. CWE IDs are
extracted with the regex `CWE-\d+`, yielding 25 tokens. Entries are kept if
`set(entry["cwe"]) & top25_set` is non-empty, which simultaneously drops entries
with an empty `cwe` list (the 222,235 cppcheck diagnostic entries from stage 4_1).

**Top-25 CWEs present in the dataset after this filter:**

| CWE | Count | Description |
|-----|-------|-------------|
| CWE-476 | 2,888 | NULL Pointer Dereference |
| CWE-20 | 186 | Improper Input Validation |
| CWE-416 | 78 | Use After Free |
| CWE-120 | 29 | Buffer Copy without Checking Size |
| CWE-121 | 22 | Stack-based Buffer Overflow |
| CWE-502 | 22 | Deserialization of Untrusted Data |
| CWE-125 | 21 | Out-of-bounds Read |
| CWE-787 | 21 | Out-of-bounds Write |
| CWE-122 | 15 | Heap-based Buffer Overflow |
| CWE-94 | 10 | Code Injection |
| CWE-78 | 1 | OS Command Injection |

codeql contributes **0** entries: its rules map to quality-oriented CWEs
(e.g. CWE-1120 "Excessive Cognitive Complexity") that are outside the top-25.

---

## Filter 2: Test File Filter

### Design Decision: Directory-component matching

Test files are identified by checking whether any **parent directory component**
of `file_path` matches a known test-tree name. The filename itself is only checked
for a small set of exact matches and substring patterns.

**Why directory-only matching?** Matching the filename substring "test" causes
false positives in projects like musl, where real POSIX API implementations have
"test" in their name:
- `src/thread/pthread_testcancel.c` — implements `pthread_testcancel(3)`, not a test
- `src/time/timespec_get.c` — implements `timespec_get(3)`, not a test

### Patterns

**Directory components** (any parent segment, case-insensitive, full match):
```
test  tests  fuzz  fuzzing  oss-fuzz  benchmark  benchmarks  testdir  spec
```

**Exact filenames** (basename only):
```
conftest.c  test.c
```

**Filename substrings** (regex on basename):
```
neontest  _fuzzer.  _fuzz.  _bench.
```

### Per-Project Examples (from top-25 subset, 105 entries dropped)

| Project | Pattern triggered | Example path |
|---------|-------------------|-------------|
| curl | dir `tests` | `tests/http/clients/h2-download.c` |
| ffmpeg | dir `tests` | `libavcodec/tests/av1_levels.c` |
| ffmpeg | filename `neontest` | `libavcodec/aarch64/neontest.c` |
| git | dir `oss-fuzz` | `oss-fuzz/fuzz-commit-graph.c` |
| git | dir `tests` | `contrib/coccinelle/tests/free.c` |
| libuv | dir `test` | `test/benchmark-async.c` |
| libuv | exact `conftest.c` | `conftest.c` |
| openssl | dir `test` | `test/sslapitest.c` |
| openssl | dir `fuzz` | `fuzz/test-corpus.c` |
| redis | dir `test` | `deps/jemalloc/test/analyze/prof_bias.c` |
| redis | dir `fuzzing` | `deps/hiredis/fuzzing/format_command_fuzzer.c` |
| tmux | dir `fuzz` | `fuzz/input-fuzzer.c` |
| vim | dir `testdir` | `runtime/syntax/testdir/input/c.c` |
| vim | exact `conftest.c` | `conftest.c` |

---

## Filter 3: `#define` Line Filter

For each entry, the script resolves
`input/repository/<project_name_with_version>/<file_path>` and reads line
`line_number` (1-indexed). If the line (stripped of leading whitespace) starts
with `#define`, the entry is dropped.

**Result: 0 entries dropped.** None of the ~3,140 post-step-2 entries land on a
`#define` line. This is expected: the top-25 CWEs correspond to runtime-safety
issues (null pointer, buffer overflow, use-after-free) reported on executable code
lines, not on macro definitions.

**Missing files: 320.** These entries could not be verified because the source file
was not found in `input/repository/`. They are **kept** (not silently dropped) to
avoid data loss. Missing files arise when the warning references a generated or
vendored file not included in the repository snapshot.

**Performance:** File contents are cached by `(project_name_with_version, file_path)` so
each source file is read at most once.

---

## Filter 4: Last Version Filter

For each `project_name`, all observed `project_version` values are sorted using
`packaging.version.Version` (semantic versioning), and the maximum is identified
as the "last version". All entries from that version are dropped.

`project_version` (e.g. `3.2.1`) is used for sorting — not `project_name_with_version`
(e.g. `openssl-openssl-3.2.1`), which has project-specific prefixes.

**Last versions removed (one per project):**

| Project | Last version | Entries dropped |
|---------|-------------|-----------------|
| curl | 8.17.0 | (part of 754 total) |
| ffmpeg | 7.1.2 | |
| git | 2.51.2 | |
| libuv | 1.51.0 | |
| musl | 1.2.5 | |
| nginx | 1.29.3 | |
| openssl | 3.6.0 | |
| redis | 8.2.2 | |
| tmux | 3.5 | |
| vim | 9.1.1896 | |

**Rationale:** The last version cannot be labeled TP/FP by the algorithm-matching
stage (no subsequent version to compare against), so entries are labeled `Unknown`.
Removing them avoids injecting unlabeled data into the annotation pipeline.

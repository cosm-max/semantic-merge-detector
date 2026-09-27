# Semantic Merge Conflict Detector — Implementation Plan

## Top-Level Overview

Build a CLI tool that takes two git branch names, diffs each branch against the merge base, extracts the "intent" of each branch's changes using heuristic/rule-based analysis, compares those intents for semantic contradictions, and outputs a Rich-formatted terminal report.

**Scope:** Implement all four source files in `src/` — they are currently empty stubs.

**Key constraints:**
- No external API calls. All intent analysis is heuristic/rule-based.
- CLI: `python src/merge_checker.py --branch-a <name> --branch-b <name> [--repo <path>]`, repo defaults to `.`
- Output: Rich formatted terminal panels and tables.
- Diff base: each branch is diffed against the common merge base (`git merge-base`), not against each other.
- Conflict detection is cross-file — intents from all changed files in both branches are compared globally.

**Dependencies (already in requirements.txt):** `gitpython`, `click`, `rich`

---

## Data Structures (shared vocabulary across all modules)

```
ChangeIntent:
  file: str                  # file path that was changed
  function: str | None       # function/method name if detectable
  change_type: str           # e.g. "value_change", "logic_inversion", "rename", "addition", "deletion", "signature_change"
  description: str           # human-readable summary of the change
  raw_diff_lines: list[str]  # the +/- lines from the diff hunk

ConflictResult:
  intent_a: ChangeIntent
  intent_b: ChangeIntent
  reason: str                # why these two intents contradict each other
  severity: str              # "HIGH" | "MEDIUM" | "LOW"
```

These are plain dataclasses (or dicts) defined in `intent_analyzer.py` and imported by the other modules.

---

## Sub-Tasks

---

### Sub-Task 1 — `src/intent_analyzer.py`

**Intent:** Parse a unified diff string into a list of `ChangeIntent` objects. This is the core semantic extraction layer. No git interaction here — it operates purely on text.

**Expected Outcomes:**
- `parse_diff(diff_text: str) -> list[ChangeIntent]` is callable and returns typed objects.
- For the demo repo's two branches (increasing discount rate vs. lowering minimum order threshold), the returned intents have distinct `change_type` values and accurate `description` strings.
- All other modules can import `ChangeIntent` and `parse_diff` from this file.

**Todo List:**
1. Define the `ChangeIntent` dataclass with fields: `file`, `function`, `change_type`, `description`, `raw_diff_lines`.
2. Write `_extract_file_path(hunk_header: str) -> str` — parses the `+++ b/<file>` line from a diff hunk.
3. Write `_extract_function_context(hunk_header: str) -> str | None` — parses the `@@ ... @@ <function_name>` part of a unified diff hunk header to find the nearest enclosing function name.
4. Write `_classify_change(removed_lines: list[str], added_lines: list[str]) -> tuple[str, str]` — returns `(change_type, description)` using these heuristics:
   - **value_change**: a numeric literal changed (regex `\d+\.?\d*`)
   - **logic_inversion**: a comparison operator flipped (`>=` → `<=`, `>` → `<`, `==` → `!=`)
   - **rename**: an identifier name changed but structure is the same
   - **addition**: lines only added, none removed
   - **deletion**: lines only removed, none added
   - **signature_change**: a function `def` line changed
   - **modification**: fallback for anything else
5. Write `parse_diff(diff_text: str) -> list[ChangeIntent]` — splits the diff by file (`diff --git` boundaries), then by hunks (`@@` boundaries), calls the helpers above on each hunk, and returns the assembled list.

**Relevant Context:**
- `demo_repo/pricing.py` on branch `feature/increase-discount` changes a numeric rate value → `change_type = "value_change"`
- `demo_repo/pricing.py` on branch `feature/lower-threshold` changes the `minimum_order` numeric value → also `change_type = "value_change"`
- `gitpython` unified diff output follows standard unified diff format

**Status:** `[x] done`

---

### Sub-Task 2 — `src/conflict_detector.py`

**Intent:** Compare two lists of `ChangeIntent` objects (one per branch) and identify semantic contradictions. This module is pure logic — no git, no I/O.

**Expected Outcomes:**
- `detect_conflicts(intents_a: list[ChangeIntent], intents_b: list[ChangeIntent]) -> list[ConflictResult]` returns a list of conflicts (empty list = no conflicts).
- The demo repo branches (both changing numeric values in the same function but for contradictory goals) produce at least one `ConflictResult`.
- `ConflictResult` dataclass is defined here and importable.

**Todo List:**
1. Define the `ConflictResult` dataclass with fields: `intent_a`, `intent_b`, `reason`, `severity`.
2. Write `_same_target(a: ChangeIntent, b: ChangeIntent) -> bool` — returns `True` if both intents touch the same `file` AND the same `function` (or both have `function = None`).
3. Write `_contradicts(a: ChangeIntent, b: ChangeIntent) -> tuple[bool, str, str]` — returns `(is_conflict, reason, severity)` using these rules:
   - Both are `value_change` in the same file/function → HIGH conflict (two devs changed the same constant differently)
   - Both are `logic_inversion` in the same file/function → HIGH conflict
   - One is `deletion` and the other is `addition` in the same file/function → MEDIUM conflict
   - Both are `signature_change` in the same file/function → HIGH conflict
   - One is `rename` and the other modifies the renamed symbol → MEDIUM conflict
   - Cross-file: if description strings share significant keywords (simple word-overlap heuristic, >50% overlap) and change types conflict → LOW conflict
4. Write `detect_conflicts(intents_a, intents_b) -> list[ConflictResult]` — iterates over all pairs `(a, b)` from the two lists, calls `_contradicts`, and collects results.

**Relevant Context:**
- Imports `ChangeIntent` from `src/intent_analyzer.py`
- For the demo repo: both branches modify numeric values inside `calculate_discount` in `pricing.py` → `_same_target` returns `True`, `_contradicts` returns HIGH

**Status:** `[x] done`

---

### Sub-Task 3 — `src/report_generator.py`

**Intent:** Render the analysis results as a Rich-formatted terminal report. This module is display-only — it takes pre-computed data and prints it.

**Expected Outcomes:**
- `generate_report(branch_a: str, branch_b: str, intents_a: list[ChangeIntent], intents_b: list[ChangeIntent], conflicts: list[ConflictResult]) -> None` prints a complete report to stdout.
- When there are no conflicts, it prints a green "No semantic conflicts detected" panel.
- When conflicts exist, it prints a colored conflict table with severity-coded rows.
- Running against the demo repo produces a readable, well-structured terminal output.

**Todo List:**
1. Import `Console`, `Panel`, `Table`, `Text` from `rich`.
2. Write `_intent_summary_table(branch_name: str, intents: list[ChangeIntent]) -> Table` — builds a Rich `Table` with columns: File, Function, Change Type, Description. One row per `ChangeIntent`.
3. Write `_conflict_table(conflicts: list[ConflictResult]) -> Table` — builds a Rich `Table` with columns: Severity, File A, Change A, File B, Change B, Reason. Rows are colored: HIGH=red, MEDIUM=yellow, LOW=cyan.
4. Write `generate_report(branch_a, branch_b, intents_a, intents_b, conflicts) -> None`:
   - Print a header panel: "Semantic Merge Conflict Detector"
   - Print two side-by-side `Panel`s (or sequential panels) for Branch A and Branch B intents using `_intent_summary_table`
   - If `conflicts` is empty: print a green `Panel` "✓ No semantic conflicts detected"
   - If `conflicts` is non-empty: print a red `Panel` header "⚠ Semantic Conflicts Detected" followed by `_conflict_table`

**Relevant Context:**
- `rich` is already in `requirements.txt`
- Severity color mapping: `"HIGH"` → `"red"`, `"MEDIUM"` → `"yellow"`, `"LOW"` → `"cyan"`

**Status:** `[x] done`

---

### Sub-Task 4 — `src/merge_checker.py`

**Intent:** The CLI entry point. Wires together git diff extraction, intent analysis, conflict detection, and report generation. This is the only module that talks to git.

**Expected Outcomes:**
- `python src/merge_checker.py --branch-a feature/increase-discount --branch-b feature/lower-threshold` runs end-to-end and prints a Rich report.
- `--repo` option defaults to `.` (current working directory).
- Graceful error messages (using Rich) for: invalid repo path, unknown branch names, branches with no diff vs. merge base.
- Exit code `0` = no conflicts, `1` = conflicts detected.

**Todo List:**
1. Write `get_diff_for_branch(repo: git.Repo, branch_name: str) -> str` using `gitpython`:
   - Find the merge base between `branch_name` and the current HEAD (or `main`) using `repo.merge_base()`
   - Return the unified diff string between the merge base commit and the tip of `branch_name` using `repo.git.diff(merge_base, branch_name)`
2. Write the `main()` Click command with options:
   - `--branch-a` (required)
   - `--branch-b` (required)
   - `--repo` (default `"."`)
3. Inside `main()`:
   - Open the repo with `git.Repo(repo_path)`
   - Call `get_diff_for_branch` for both branches
   - Call `parse_diff` on each diff string
   - Call `detect_conflicts` with both intent lists
   - Call `generate_report`
   - Call `sys.exit(1)` if conflicts were found
4. Add a `if __name__ == "__main__": main()` guard.

**Relevant Context:**
- `gitpython` docs: `repo.merge_base(a, b)` returns a list of commits; use `[0]` for the first
- `repo.git.diff(base_commit, branch)` returns unified diff text
- Imports: `parse_diff` from `intent_analyzer`, `detect_conflicts` from `conflict_detector`, `generate_report` from `report_generator`

**Status:** `[x] done`

---

## Module Dependency Graph

```
merge_checker.py  (CLI, git I/O)
    |
    |-- intent_analyzer.py   (diff parsing, ChangeIntent)
    |-- conflict_detector.py (comparison, ConflictResult) <-- imports ChangeIntent
    |-- report_generator.py  (Rich output)               <-- imports both dataclasses
```

Each module is independently testable. `intent_analyzer` has zero external dependencies beyond the stdlib. `conflict_detector` only imports from `intent_analyzer`. `report_generator` only imports from `intent_analyzer` and `conflict_detector`. `merge_checker` imports from all three and is the only module touching git.

---

## Test Scenario (demo_repo)

```
python src/merge_checker.py \
  --branch-a feature/increase-discount \
  --branch-b feature/lower-threshold \
  --repo ./demo_repo
```

Expected: Both branches modify numeric values in `calculate_discount` / `get_discount_rate` in `pricing.py`. The detector should flag a HIGH severity semantic conflict because both branches changed numeric thresholds/rates in the same pricing logic in contradictory directions.

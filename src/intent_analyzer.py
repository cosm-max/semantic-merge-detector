"""
intent_analyzer.py

Parses a unified git diff string into structured ChangeIntent objects.
All analysis is heuristic/rule-based — no external API calls.

Public API
----------
ChangeIntent  : dataclass representing one inferred intent per diff hunk
parse_diff    : ChangeIntent list from raw unified diff text
analyze_intent: high-level dict result (changed files, functions, summaries)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ChangeIntent:
    """Represents the inferred intent behind a single diff hunk."""
    file: str
    function: Optional[str]          # nearest enclosing function, if detectable
    change_type: str                 # see _classify_change for possible values
    description: str                 # human-readable summary of what changed
    raw_diff_lines: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Matches:  +++ b/path/to/file.py   or   +++ /path/to/file.py (no b/ prefix)
_FILE_RE = re.compile(r'^\+\+\+\s+(?:b/)?(.+)$')

# Matches:  @@ -l,s +l,s @@ optional_function_name
_HUNK_RE = re.compile(r'^@@[^@]*@@\s*(.*)')

# Numeric literals (integers or decimals)
_NUMBER_RE = re.compile(r'\b\d+\.?\d*\b')

# Comparison operators we care about for logic-inversion detection
_CMP_OPS = re.compile(r'(>=|<=|!=|==|>(?!=)|<(?!=))')

# Python def/class line
_DEF_RE = re.compile(r'^\s*(?:def|class)\s+(\w+)')

# Simple identifier token
_IDENT_RE = re.compile(r'\b([A-Za-z_]\w*)\b')


def _extract_file_path(line: str) -> Optional[str]:
    """Return the file path from a '+++ b/...' line, or None if no match."""
    m = _FILE_RE.match(line.strip())
    return m.group(1) if m else None


def _extract_function_context(hunk_header: str) -> Optional[str]:
    """
    Parse the function-context portion of a unified diff hunk header.

    A hunk header looks like:
        @@ -5,8 +5,8 @@ def get_discount_rate(customer_type):
    The text after the second '@@' is the nearest enclosing scope that git
    detected.  We extract the first identifier that follows 'def' or 'class',
    falling back to the raw token if neither keyword is present.
    """
    m = _HUNK_RE.match(hunk_header.strip())
    if not m:
        return None
    context = m.group(1).strip()
    if not context:
        return None
    # Prefer the name after 'def' or 'class'
    def_m = _DEF_RE.match(context)
    if def_m:
        return def_m.group(1)
    # Fall back to first identifier-looking token
    tok = _IDENT_RE.search(context)
    return tok.group(1) if tok else None


def _numbers_in(lines: list[str]) -> list[str]:
    """Return all numeric literals found across a list of lines."""
    result = []
    for line in lines:
        result.extend(_NUMBER_RE.findall(line))
    return result


def _operators_in(lines: list[str]) -> list[str]:
    """Return all comparison operators found across a list of lines."""
    result = []
    for line in lines:
        result.extend(_CMP_OPS.findall(line))
    return result


def _identifiers_in(lines: list[str]) -> set[str]:
    """Return the set of all identifier tokens in a list of lines."""
    tokens: set[str] = set()
    for line in lines:
        tokens.update(_IDENT_RE.findall(line))
    return tokens


def _strip_prefix(lines: list[str], prefix: str) -> list[str]:
    """Strip the leading +/- character from diff lines."""
    return [l[1:] if l.startswith(prefix) else l for l in lines]


def _classify_change(
    removed_lines: list[str],
    added_lines: list[str],
) -> tuple[str, str]:
    """
    Infer the type and a human-readable description of a change.

    Returns (change_type, description).

    change_type values (in priority order):
      signature_change  – a 'def' or 'class' line itself changed
      logic_inversion   – a comparison operator was flipped
      value_change      – a numeric literal changed
      rename            – an identifier name changed, structure is the same
      addition          – lines only added, nothing removed
      deletion          – lines only removed, nothing added
      modification      – catch-all
    """
    # Strip the +/- diff prefix for content inspection
    removed = _strip_prefix(removed_lines, '-')
    added   = _strip_prefix(added_lines,   '+')

    # --- signature_change ---
    removed_defs = [l for l in removed if _DEF_RE.match(l)]
    added_defs   = [l for l in added   if _DEF_RE.match(l)]
    if removed_defs and added_defs:
        old_name = _DEF_RE.match(removed_defs[0]).group(1)
        new_name = _DEF_RE.match(added_defs[0]).group(1)
        if old_name != new_name:
            return (
                "signature_change",
                f"Renamed '{old_name}' to '{new_name}'.",
            )
        return (
            "signature_change",
            f"Changed signature of '{old_name}'.",
        )

    # --- pure addition / deletion ---
    if not removed_lines:
        snippet = added_lines[0].lstrip('+ ').strip() if added_lines else ''
        desc = f"Added new code: {snippet!r}." if snippet else "Added new lines."
        return "addition", desc
    if not added_lines:
        snippet = removed_lines[0].lstrip('- ').strip() if removed_lines else ''
        desc = f"Removed code: {snippet!r}." if snippet else "Deleted lines."
        return "deletion", desc

    # --- logic_inversion ---
    old_ops = _operators_in(removed)
    new_ops = _operators_in(added)
    if old_ops and new_ops and old_ops != new_ops:
        return (
            "logic_inversion",
            f"Flipped condition from '{old_ops[0]}' to '{new_ops[0]}'.",
        )

    # --- value_change ---
    old_nums = _numbers_in(removed)
    new_nums = _numbers_in(added)
    if old_nums and new_nums and old_nums != new_nums:
        changed_pairs = [
            f"{o} → {n}"
            for o, n in zip(old_nums, new_nums)
            if o != n
        ]
        if changed_pairs:
            pair_str = ", ".join(changed_pairs[:3])  # cap at 3 for readability
            return "value_change", f"Changed numeric value: {pair_str}."

    # --- rename ---
    old_ids = _identifiers_in(removed)
    new_ids = _identifiers_in(added)
    only_old = old_ids - new_ids
    only_new = new_ids - old_ids
    # Treat as rename when exactly one identifier was swapped out
    if len(only_old) == 1 and len(only_new) == 1:
        old_id, new_id = next(iter(only_old)), next(iter(only_new))
        return "rename", f"Renamed identifier '{old_id}' to '{new_id}'."

    # --- modification (fallback) ---
    return "modification", "Modified existing logic."


# ---------------------------------------------------------------------------
# Core parsing functions
# ---------------------------------------------------------------------------

def parse_diff(diff_text: str) -> list[ChangeIntent]:
    """
    Parse a unified diff string into a list of ChangeIntent objects.

    One ChangeIntent is produced per diff hunk (a @@ ... @@ block).
    """
    if not diff_text or not diff_text.strip():
        return []

    intents: list[ChangeIntent] = []

    # Split into per-file sections on 'diff --git' boundaries
    file_sections = re.split(r'(?=^diff --git )', diff_text, flags=re.MULTILINE)

    for section in file_sections:
        if not section.strip():
            continue

        lines = section.splitlines()
        current_file: Optional[str] = None

        # Locate the +++ line to get the file path
        for line in lines:
            path = _extract_file_path(line)
            if path:
                current_file = path
                break

        if current_file is None:
            continue

        # Split section into hunks on @@ boundaries
        hunk_chunks = re.split(r'(?=^@@)', section, flags=re.MULTILINE)

        for chunk in hunk_chunks:
            chunk_lines = chunk.splitlines()
            if not chunk_lines:
                continue
            header = chunk_lines[0]
            if not header.startswith('@@'):
                continue

            function_ctx = _extract_function_context(header)

            removed_lines = [l for l in chunk_lines[1:] if l.startswith('-')]
            added_lines   = [l for l in chunk_lines[1:] if l.startswith('+')]

            change_type, description = _classify_change(removed_lines, added_lines)

            intents.append(ChangeIntent(
                file=current_file,
                function=function_ctx,
                change_type=change_type,
                description=description,
                raw_diff_lines=[l for l in chunk_lines[1:] if l.startswith(('+', '-'))],
            ))

    return intents


# ---------------------------------------------------------------------------
# High-level public API
# ---------------------------------------------------------------------------

def analyze_intent(diff_text: str) -> dict:
    """
    Analyze a git diff string and return a structured intent report.

    Returns
    -------
    dict with keys:
      changed_files   : list[str]  – deduplicated list of file paths touched
      changed_functions: list[str] – deduplicated list of function/method names
      change_intents  : list[dict] – one entry per hunk, with keys:
                          file, function, change_type, description
      branch_intent   : str        – one-sentence overall summary of the branch
    """
    intents = parse_diff(diff_text)

    if not intents:
        return {
            "changed_files": [],
            "changed_functions": [],
            "change_intents": [],
            "branch_intent": "No changes detected.",
        }

    changed_files: list[str] = []
    seen_files: set[str] = set()
    changed_functions: list[str] = []
    seen_functions: set[str] = set()

    for intent in intents:
        if intent.file not in seen_files:
            changed_files.append(intent.file)
            seen_files.add(intent.file)
        if intent.function and intent.function not in seen_functions:
            changed_functions.append(intent.function)
            seen_functions.add(intent.function)

    change_intents = [
        {
            "file": i.file,
            "function": i.function,
            "change_type": i.change_type,
            "description": i.description,
        }
        for i in intents
    ]

    branch_intent = _summarize_branch(intents)

    return {
        "changed_files": changed_files,
        "changed_functions": changed_functions,
        "change_intents": change_intents,
        "branch_intent": branch_intent,
    }


def _summarize_branch(intents: list[ChangeIntent]) -> str:
    """
    Produce a single human-readable sentence describing what the branch
    is trying to accomplish overall, based on the aggregated change types.
    """
    if not intents:
        return "No changes detected."

    type_counts: dict[str, int] = {}
    for i in intents:
        type_counts[i.change_type] = type_counts.get(i.change_type, 0) + 1

    dominant_type = max(type_counts, key=lambda t: type_counts[t])
    files_touched = len({i.file for i in intents})
    fns_touched   = len({i.function for i in intents if i.function})

    scope = (
        f"in {files_touched} file(s)"
        if fns_touched == 0
        else f"across {fns_touched} function(s) in {files_touched} file(s)"
    )

    type_phrases = {
        "value_change":      f"Adjusts numeric constants or threshold values {scope}.",
        "logic_inversion":   f"Inverts or reverses conditional logic {scope}.",
        "signature_change":  f"Modifies function or class signatures {scope}.",
        "rename":            f"Renames identifiers {scope}.",
        "addition":          f"Adds new code or functionality {scope}.",
        "deletion":          f"Removes existing code {scope}.",
        "modification":      f"Refactors or modifies existing logic {scope}.",
    }

    return type_phrases.get(dominant_type, f"Makes {dominant_type} changes {scope}.")

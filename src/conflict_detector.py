"""
conflict_detector.py

Compares two intent analysis results (from intent_analyzer.analyze_intent)
and identifies semantic conflicts between them.

All analysis is heuristic/rule-based — no external API calls.

Public API
----------
ConflictResult  : dataclass representing one detected semantic conflict
detect_conflicts: compare two analyze_intent dicts → conflict report dict
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Semantic vocabulary for domain classification
# ---------------------------------------------------------------------------

# Keywords that suggest a value represents a rate, multiplier or percentage
_RATE_KEYWORDS = frozenset({
    "rate", "ratio", "percent", "percentage", "factor", "multiplier",
    "discount", "fee", "tax", "markup", "margin", "coefficient",
})

# Keywords that suggest a value is a threshold, limit or boundary
_THRESHOLD_KEYWORDS = frozenset({
    "threshold", "limit", "minimum", "maximum", "min", "max",
    "floor", "ceiling", "cap", "cutoff", "boundary", "order",
    "quota", "budget", "amount", "total",
})

# Keywords in description/diff that signal a condition change
_CONDITION_KEYWORDS = frozenset({
    "condition", "if", "else", "check", "guard", "flipped", "inverted",
    "comparison", "operator", ">=", "<=", "!=", "==",
})

# Stopwords excluded from keyword-overlap scoring
_STOPWORDS = frozenset({
    "a", "an", "the", "in", "of", "to", "and", "or", "is", "was",
    "it", "for", "on", "with", "as", "at", "by", "from", "that",
    "this", "be", "are", "were", "has", "have", "had", "not",
    "changed", "change", "code", "new", "existing", "lines",
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConflictResult:
    """Represents one detected semantic conflict between two branches."""
    intent_a: dict                  # the change_intent entry from branch A
    intent_b: dict                  # the change_intent entry from branch B
    conflict_type: str              # machine-readable conflict category
    severity: str                   # "HIGH" | "MEDIUM" | "LOW"
    explanation: str                # human-readable explanation
    recommendation: str             # what the developers should do
    affected_files: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _tokens(text: str) -> set[str]:
    """Lowercase word tokens from a string, stopwords removed."""
    words = re.findall(r'\b[a-z_]\w*\b', text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _domain_of(intent_entry: dict) -> str:
    """
    Classify an intent entry as 'rate', 'threshold', 'condition',
    'structure', or 'other' based on its description and raw diff content.
    """
    text = intent_entry.get("description", "").lower()
    change_type = intent_entry.get("change_type", "")

    if change_type in ("logic_inversion",):
        return "condition"
    if change_type in ("signature_change",):
        return "structure"

    toks = _tokens(text)

    if toks & _RATE_KEYWORDS:
        return "rate"
    if toks & _THRESHOLD_KEYWORDS:
        return "threshold"
    if toks & _CONDITION_KEYWORDS:
        return "condition"
    return "other"


def _same_file(a: dict, b: dict) -> bool:
    return a.get("file") == b.get("file")


def _same_function(a: dict, b: dict) -> bool:
    """
    True when both intents name the same function, OR when neither names one
    (both are file-level changes in the same file).
    """
    fn_a = a.get("function")
    fn_b = b.get("function")
    return fn_a == fn_b  # handles (None, None) → True when same file


def _shared_file_or_function(a: dict, b: dict) -> bool:
    """True when the two intents overlap in file or function scope."""
    if _same_file(a, b):
        return True
    # Cross-file: check if they name the same function in different files
    fn_a, fn_b = a.get("function"), b.get("function")
    if fn_a and fn_b and fn_a == fn_b:
        return True
    return False


def _description_overlap(a: dict, b: dict) -> float:
    """
    Jaccard similarity of meaningful word tokens between two descriptions.
    Returns a value in [0.0, 1.0].
    """
    toks_a = _tokens(a.get("description", ""))
    toks_b = _tokens(b.get("description", ""))
    if not toks_a or not toks_b:
        return 0.0
    intersection = toks_a & toks_b
    union = toks_a | toks_b
    return len(intersection) / len(union)


def _affected_files(a: dict, b: dict) -> list[str]:
    """Deduplicated sorted list of files touched by both intents."""
    files: set[str] = set()
    if a.get("file"):
        files.add(a["file"])
    if b.get("file"):
        files.add(b["file"])
    return sorted(files)


# ---------------------------------------------------------------------------
# Conflict detection rules
# Each rule is a function:  (intent_a, intent_b) -> ConflictResult | None
# Rules are evaluated in order; first match wins for a given pair.
# ---------------------------------------------------------------------------

def _rule_same_value_same_scope(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    HIGH — Both branches changed a numeric value in the same file/function.
    Classic case: two devs independently tweaked the same constant.
    """
    if a["change_type"] != "value_change" or b["change_type"] != "value_change":
        return None
    if not _same_file(a, b):
        return None
    fn_a, fn_b = a.get("function"), b.get("function")
    scope = (
        f"function '{fn_a}'" if fn_a
        else f"file '{a['file']}'"
    )
    return ConflictResult(
        intent_a=a,
        intent_b=b,
        conflict_type="concurrent_value_change",
        severity="HIGH",
        explanation=(
            f"Both branches independently changed numeric values in the same "
            f"{scope}. The changes may contradict each other at runtime: "
            f"Branch A: {a['description']} "
            f"Branch B: {b['description']}"
        ),
        recommendation=(
            "Review both numeric changes together. Decide on a single agreed "
            "value (or range), implement it in one commit, and discard the "
            "other branch's change to that constant."
        ),
        affected_files=_affected_files(a, b),
    )


def _rule_rate_vs_threshold(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    HIGH — One branch changes a rate/percentage while the other changes a
    threshold/limit in the same file.  Together they alter the effective
    outcome of the same business rule from two different angles.
    """
    if not _same_file(a, b):
        return None
    dom_a, dom_b = _domain_of(a), _domain_of(b)
    is_rate_threshold = (
        (dom_a == "rate" and dom_b == "threshold") or
        (dom_a == "threshold" and dom_b == "rate")
    )
    if not is_rate_threshold:
        return None
    rate_entry      = a if dom_a == "rate"      else b
    threshold_entry = a if dom_a == "threshold" else b
    return ConflictResult(
        intent_a=a,
        intent_b=b,
        conflict_type="rate_threshold_interaction",
        severity="HIGH",
        explanation=(
            f"One branch adjusts a rate/percentage ({rate_entry['description']}) "
            f"while the other adjusts a threshold/limit "
            f"({threshold_entry['description']}) in '{a['file']}'. "
            "These two values interact to determine the final computed outcome — "
            "changing both independently can produce an unintended combined effect."
        ),
        recommendation=(
            "Calculate the combined effect of both changes before merging. "
            "Agree on the intended business outcome, then set both the rate "
            "and the threshold in a single coordinated change with shared tests."
        ),
        affected_files=_affected_files(a, b),
    )


def _rule_condition_vs_body(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    MEDIUM — One branch changes a condition (logic_inversion) while the other
    modifies code inside the same conditional block (value_change / modification).
    The condition change may make the body change unreachable or always-executed.
    """
    if not _same_file(a, b):
        return None
    types = {a["change_type"], b["change_type"]}
    has_condition = "logic_inversion" in types
    has_body      = bool(types & {"value_change", "modification", "addition", "deletion"})
    if not (has_condition and has_body):
        return None
    cond_entry = a if a["change_type"] == "logic_inversion" else b
    body_entry = b if a["change_type"] == "logic_inversion" else a
    return ConflictResult(
        intent_a=a,
        intent_b=b,
        conflict_type="condition_body_conflict",
        severity="MEDIUM",
        explanation=(
            f"Branch A/B flips a condition ({cond_entry['description']}) "
            f"while the other modifies code that executes inside that block "
            f"({body_entry['description']}) in '{a['file']}'. "
            "The condition change may make the body change always active, "
            "never active, or active under completely different circumstances."
        ),
        recommendation=(
            "Trace the control flow with both changes applied. Verify the "
            "body change still executes under the intended circumstances after "
            "the condition is flipped, and add a test that covers the boundary."
        ),
        affected_files=_affected_files(a, b),
    )


def _rule_addition_depends_on_deletion(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    MEDIUM — One branch adds code that likely depends on something the other
    branch deletes (or vice versa), in the same file.
    """
    if not _same_file(a, b):
        return None
    types = {a["change_type"], b["change_type"]}
    if types != {"addition", "deletion"}:
        return None
    add_entry = a if a["change_type"] == "addition" else b
    del_entry = b if a["change_type"] == "addition" else a
    return ConflictResult(
        intent_a=a,
        intent_b=b,
        conflict_type="add_delete_dependency",
        severity="MEDIUM",
        explanation=(
            f"One branch adds new code ({add_entry['description']}) "
            f"while the other removes code ({del_entry['description']}) "
            f"in '{a['file']}'. The new code may depend on what was removed, "
            "causing a runtime error or silent behaviour change."
        ),
        recommendation=(
            "Check whether the added code references anything that was deleted. "
            "If there is a dependency, the deletion must be reconsidered or the "
            "addition must be updated to work without the removed code."
        ),
        affected_files=_affected_files(a, b),
    )


def _rule_concurrent_signature_change(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    HIGH — Both branches change the same function's signature.
    Call-sites updated by one branch will be broken by the other.
    """
    if a["change_type"] != "signature_change" or b["change_type"] != "signature_change":
        return None
    if not _same_file(a, b):
        return None
    return ConflictResult(
        intent_a=a,
        intent_b=b,
        conflict_type="concurrent_signature_change",
        severity="HIGH",
        explanation=(
            f"Both branches modify the signature of the same function/class "
            f"in '{a['file']}'. "
            f"Branch A: {a['description']} "
            f"Branch B: {b['description']} "
            "Merging both will produce a compile/runtime error at every call-site."
        ),
        recommendation=(
            "Agree on a single final signature. One approach: merge the more "
            "additive change first (e.g. adding a parameter with a default), "
            "then layer the other change on top. Update all call-sites once."
        ),
        affected_files=_affected_files(a, b),
    )


def _rule_cross_file_semantic_overlap(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    LOW — Different files, but the descriptions share enough semantic keywords
    to suggest the two branches are working on the same conceptual feature.
    Jaccard similarity > 0.35 threshold (generous for short descriptions).
    """
    if _same_file(a, b):
        return None  # already covered by higher-priority same-file rules
    overlap = _description_overlap(a, b)
    if overlap <= 0.35:
        return None
    return ConflictResult(
        intent_a=a,
        intent_b=b,
        conflict_type="cross_file_semantic_overlap",
        severity="LOW",
        explanation=(
            f"Changes in '{a['file']}' and '{b['file']}' appear to target "
            f"the same concept (description similarity: {overlap:.0%}). "
            f"Branch A: {a['description']} "
            f"Branch B: {b['description']} "
            "They may produce an unintended combined effect even though they "
            "touch different files."
        ),
        recommendation=(
            "Review both changes in the context of the same feature. "
            "Run integration tests that exercise both files together to confirm "
            "the combined behaviour is intentional."
        ),
        affected_files=_affected_files(a, b),
    )


# Ordered rule list — specific high-severity rules first
_RULES = [
    _rule_concurrent_signature_change,
    _rule_rate_vs_threshold,
    _rule_same_value_same_scope,
    _rule_condition_vs_body,
    _rule_addition_depends_on_deletion,
    _rule_cross_file_semantic_overlap,
]


# ---------------------------------------------------------------------------
# Core comparison engine
# ---------------------------------------------------------------------------

def _compare_pair(a: dict, b: dict) -> Optional[ConflictResult]:
    """
    Run all rules against a single (intent_a, intent_b) pair.
    Returns the first matching ConflictResult, or None.
    """
    for rule in _RULES:
        result = rule(a, b)
        if result is not None:
            return result
    return None


def _collect_intents(intent_result: dict) -> list[dict]:
    """Extract the list of change_intent dicts from an analyze_intent result."""
    return intent_result.get("change_intents", [])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_conflicts(intent_a: dict, intent_b: dict) -> dict:
    """
    Compare two analyze_intent() results and return a conflict report.

    Parameters
    ----------
    intent_a : dict
        Result of intent_analyzer.analyze_intent() for branch A.
    intent_b : dict
        Result of intent_analyzer.analyze_intent() for branch B.

    Returns
    -------
    dict with keys:
      conflict_found  : bool
      severity        : str   — "HIGH" | "MEDIUM" | "LOW" | "NONE"
      explanation     : str   — human-readable summary of all conflicts found
      affected_files  : list[str]
      recommendation  : str   — consolidated action item for developers
      conflicts       : list[dict]  — one entry per detected conflict, each with:
                          conflict_type, severity, explanation,
                          recommendation, affected_files,
                          intent_a (the specific hunk), intent_b (the specific hunk)
    """
    intents_a = _collect_intents(intent_a)
    intents_b = _collect_intents(intent_b)

    raw_conflicts: list[ConflictResult] = []

    for a in intents_a:
        for b in intents_b:
            result = _compare_pair(a, b)
            if result is not None:
                raw_conflicts.append(result)

    if not raw_conflicts:
        return {
            "conflict_found": False,
            "severity": "NONE",
            "explanation": (
                "No semantic conflicts detected. The two branches appear to "
                "make independent changes that are safe to merge."
            ),
            "affected_files": [],
            "recommendation": "Proceed with the merge normally.",
            "conflicts": [],
        }

    # Aggregate severity: worst single conflict determines the overall level
    _SEV_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    overall_severity = max(
        raw_conflicts, key=lambda c: _SEV_RANK.get(c.severity, 0)
    ).severity

    # Deduplicate affected files across all conflicts
    all_files: set[str] = set()
    for c in raw_conflicts:
        all_files.update(c.affected_files)

    # Build the serialisable conflict list
    conflicts_out = [
        {
            "conflict_type":  c.conflict_type,
            "severity":       c.severity,
            "explanation":    c.explanation,
            "recommendation": c.recommendation,
            "affected_files": c.affected_files,
            "intent_a":       c.intent_a,
            "intent_b":       c.intent_b,
        }
        for c in raw_conflicts
    ]

    # Consolidated explanation: lead with count, list each conflict's first sentence
    count = len(raw_conflicts)
    lead = (
        f"Found {count} semantic conflict{'s' if count > 1 else ''} "
        f"(overall severity: {overall_severity})."
    )
    bullets = "\n".join(
        f"  [{c.severity}] {c.explanation.split('.')[0]}."
        for c in raw_conflicts
    )
    explanation = f"{lead}\n{bullets}"

    # Pick the most critical recommendation
    top = max(raw_conflicts, key=lambda c: _SEV_RANK.get(c.severity, 0))
    recommendation = top.recommendation

    return {
        "conflict_found": True,
        "severity":       overall_severity,
        "explanation":    explanation,
        "affected_files": sorted(all_files),
        "recommendation": recommendation,
        "conflicts":      conflicts_out,
    }

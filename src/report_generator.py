"""
report_generator.py

Renders a semantic merge conflict report to the terminal using Rich.

Public API
----------
generate_report(conflict_result, branch_a_name, branch_b_name,
                intent_a=None, intent_b=None) -> None
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.columns import Columns
from rich import box

console = Console()

# Severity → Rich colour string
_SEV_COLOUR = {
    "HIGH":   "bold red",
    "MEDIUM": "bold yellow",
    "LOW":    "bold cyan",
    "NONE":   "bold green",
}

# change_type → short readable label
_TYPE_LABEL = {
    "value_change":     "Value Change",
    "logic_inversion":  "Logic Inversion",
    "signature_change": "Signature Change",
    "rename":           "Rename",
    "addition":         "Addition",
    "deletion":         "Deletion",
    "modification":     "Modification",
}

# conflict_type → short readable label
_CONFLICT_LABEL = {
    "concurrent_value_change":    "Concurrent Value Change",
    "rate_threshold_interaction":  "Rate / Threshold Interaction",
    "condition_body_conflict":     "Condition vs Body",
    "add_delete_dependency":       "Add / Delete Dependency",
    "concurrent_signature_change": "Concurrent Signature Change",
    "cross_file_semantic_overlap": "Cross-file Semantic Overlap",
}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _sev_badge(severity: str) -> Text:
    """Return a coloured severity badge as a Rich Text object."""
    colour = _SEV_COLOUR.get(severity, "white")
    return Text(f" {severity} ", style=f"on {colour.replace('bold ', '')} bold white")


def _intent_panel(branch_name: str, intent: dict | None, colour: str) -> Panel:
    """
    Build a Rich Panel summarising one branch's intent analysis.
    `intent` is the dict returned by analyze_intent(), or None if unavailable.
    """
    if intent is None or not intent.get("change_intents"):
        body = Text("No changes detected.", style="dim")
        return Panel(body, title=f"[bold {colour}]{branch_name}[/]",
                     border_style=colour, expand=True)

    branch_summary = intent.get("branch_intent", "—")

    tbl = Table(box=box.SIMPLE, show_header=True, header_style=f"bold {colour}",
                expand=True, padding=(0, 1))
    tbl.add_column("File",        style="dim", no_wrap=True)
    tbl.add_column("Function",    style="dim")
    tbl.add_column("Change Type", style="bold")
    tbl.add_column("Description")

    for ci in intent["change_intents"]:
        fn          = ci.get("function") or "—"
        ctype       = _TYPE_LABEL.get(ci.get("change_type", ""), ci.get("change_type", ""))
        description = ci.get("description", "")
        tbl.add_row(ci.get("file", ""), fn, ctype, description)

    from rich.console import Group
    body = Group(
        Text(f"Intent: {branch_summary}", style=f"{colour}"),
        Text(""),
        tbl,
    )
    return Panel(body, title=f"[bold {colour}]{branch_name}[/]",
                 border_style=colour, expand=True)


def _conflict_detail_panel(conflict: dict, index: int, total: int) -> Panel:
    """Render one individual conflict entry as a Panel."""
    severity    = conflict.get("severity", "LOW")
    ctype       = conflict.get("conflict_type", "")
    label       = _CONFLICT_LABEL.get(ctype, ctype.replace("_", " ").title())
    colour      = _SEV_COLOUR.get(severity, "white")
    explanation = conflict.get("explanation", "")
    rec         = conflict.get("recommendation", "")
    files       = conflict.get("affected_files", [])

    from rich.console import Group
    body = Group(
        Text(explanation, style="white"),
        Text(""),
        Text("Affected files: " + (", ".join(files) if files else "—"), style="dim"),
        Text(""),
        Text("Recommendation:", style="bold"),
        Text(rec, style="italic"),
    )
    title = f"[{colour}]Conflict {index}/{total}  ·  {label}  ·  {severity}[/]"
    return Panel(body, title=title, border_style=colour.replace("bold ", ""),
                 expand=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_report(
    conflict_result: dict,
    branch_a_name: str,
    branch_b_name: str,
    intent_a: dict | None = None,
    intent_b: dict | None = None,
) -> None:
    """
    Print a Rich-formatted semantic merge conflict report to the terminal.

    Parameters
    ----------
    conflict_result : dict
        The dict returned by conflict_detector.detect_conflicts().
    branch_a_name   : str
        Human-readable name for branch A (e.g. 'feature/increase-discount').
    branch_b_name   : str
        Human-readable name for branch B (e.g. 'feature/lower-threshold').
    intent_a        : dict | None
        Optional analyze_intent() result for branch A — used to populate the
        branch summary panels.  May be omitted if not available.
    intent_b        : dict | None
        Optional analyze_intent() result for branch B.
    """
    # ── Header ────────────────────────────────────────────────────────────────
    console.print()
    console.print(Rule(
        "[bold white on dark_blue]  SEMANTIC MERGE CONFLICT REPORT  [/]",
        style="dark_blue",
    ))
    console.print()

    # ── Branch intent summaries (side by side where terminal is wide enough) ─
    panel_a = _intent_panel(branch_a_name, intent_a, "blue")
    panel_b = _intent_panel(branch_b_name, intent_b, "green")
    console.print(Columns([panel_a, panel_b], equal=True, expand=True))
    console.print()

    # ── No conflict ──────────────────────────────────────────────────────────
    if not conflict_result.get("conflict_found"):
        console.print(Panel(
            Text.assemble(
                Text("✔  ALL CLEAR\n\n", style="bold green"),
                Text(
                    conflict_result.get(
                        "explanation",
                        "No semantic conflicts detected. Safe to merge."
                    ),
                    style="green",
                ),
                Text("\n\n"),
                Text("Recommendation: ", style="bold"),
                Text(conflict_result.get("recommendation", "Proceed with the merge normally.")),
            ),
            title="[bold green]Result[/]",
            border_style="green",
            expand=True,
        ))
        console.print()
        return

    # ── Conflict summary header ───────────────────────────────────────────────
    overall_sev    = conflict_result.get("severity", "HIGH")
    overall_colour = _SEV_COLOUR.get(overall_sev, "bold red")
    total_count    = len(conflict_result.get("conflicts", []))
    affected_files = conflict_result.get("affected_files", [])

    summary_body = Text.assemble(
        Text("⚠  SEMANTIC CONFLICTS DETECTED\n\n", style=f"{overall_colour}"),
        Text("Overall severity:  ", style="bold"),
        _sev_badge(overall_sev),
        Text("\n"),
        Text("Conflicts found:   ", style="bold"),
        Text(str(total_count), style=overall_colour),
        Text("\n"),
        Text("Affected files:    ", style="bold"),
        Text(
            ", ".join(affected_files) if affected_files else "—",
            style="dim",
        ),
        Text("\n\n"),
        Text("Summary:\n", style="bold"),
        Text(conflict_result.get("explanation", ""), style="white"),
    )
    console.print(Panel(
        summary_body,
        title=f"[{overall_colour}]⚠  Conflict Summary[/]",
        border_style=overall_colour.replace("bold ", ""),
        expand=True,
    ))
    console.print()

    # ── Per-conflict detail panels ────────────────────────────────────────────
    conflicts = conflict_result.get("conflicts", [])
    for idx, conflict in enumerate(conflicts, start=1):
        console.print(_conflict_detail_panel(conflict, idx, total_count))
        console.print()

    # ── Consolidated recommendation ───────────────────────────────────────────
    recommendation = conflict_result.get("recommendation", "")
    if recommendation:
        console.print(Panel(
            Text.assemble(
                Text("What to do next:\n\n", style="bold"),
                Text(recommendation, style="italic"),
            ),
            title="[bold]Recommendation[/]",
            border_style="bright_white",
            expand=True,
        ))
        console.print()

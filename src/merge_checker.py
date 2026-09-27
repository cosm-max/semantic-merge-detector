"""
merge_checker.py

CLI entry point for the Semantic Merge Conflict Detector.

Usage
-----
    python3 src/merge_checker.py <branch_a> <branch_b> [--repo-path <path>]

Exit codes
----------
    0  – no semantic conflicts detected
    1  – one or more semantic conflicts detected
    2  – usage error (bad repo path, unknown branch, etc.)
"""

from __future__ import annotations

import sys
import os

# Allow sibling modules (intent_analyzer, conflict_detector, report_generator)
# to be imported directly when this file is run as a script from any directory.
sys.path.insert(0, os.path.dirname(__file__))

import click
import git
from rich.console import Console

from intent_analyzer import analyze_intent
from conflict_detector import detect_conflicts
from report_generator import generate_report

_err = Console(stderr=True)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _open_repo(repo_path: str) -> git.Repo:
    """Open a git.Repo at *repo_path*, or exit with a clear error message."""
    try:
        return git.Repo(repo_path, search_parent_directories=False)
    except git.InvalidGitRepositoryError:
        _err.print(f"[bold red]Error:[/] '{repo_path}' is not a git repository.")
        sys.exit(2)
    except git.NoSuchPathError:
        _err.print(f"[bold red]Error:[/] Path '{repo_path}' does not exist.")
        sys.exit(2)


def _resolve_branch(repo: git.Repo, branch_name: str) -> git.refs.symbolic.SymbolicReference:
    """
    Return the reference for *branch_name*, or exit with a clear error.
    Accepts both local branch names and remote-tracking refs.
    """
    try:
        return repo.commit(branch_name)
    except (git.BadName, git.BadObject, ValueError):
        _err.print(
            f"[bold red]Error:[/] Branch or ref '{branch_name}' not found in the repository."
        )
        sys.exit(2)


def _get_diff(repo: git.Repo, base_commit: git.Commit, branch_name: str) -> str:
    """Return the unified diff between *base_commit* and the tip of *branch_name*."""
    return repo.git.diff(base_commit.hexsha, branch_name)


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

@click.command()
@click.argument("branch_a")
@click.argument("branch_b")
@click.option(
    "--repo-path",
    default=".",
    show_default=True,
    help="Path to the local git repository (defaults to current directory).",
)
def main(branch_a: str, branch_b: str, repo_path: str) -> None:
    """
    Detect semantic merge conflicts between BRANCH_A and BRANCH_B.

    Each branch is diffed against their common merge base.  The intent of
    each set of changes is analysed with heuristic rules and compared for
    contradictions.  A Rich-formatted report is printed to the terminal.
    """
    repo = _open_repo(repo_path)

    # Validate both branches exist before doing any diff work
    _resolve_branch(repo, branch_a)
    _resolve_branch(repo, branch_b)

    # Find the common ancestor
    merge_bases = repo.merge_base(branch_a, branch_b)
    if not merge_bases:
        _err.print(
            "[bold red]Error:[/] No common merge base found between "
            f"'{branch_a}' and '{branch_b}'. Do they share any history?"
        )
        sys.exit(2)
    base_commit: git.Commit = merge_bases[0]

    # Collect diffs from merge base → tip of each branch
    diff_a = _get_diff(repo, base_commit, branch_a)
    diff_b = _get_diff(repo, base_commit, branch_b)

    if not diff_a.strip() and not diff_b.strip():
        _err.print("[yellow]Warning:[/] Both branches are identical to their merge base — nothing to compare.")
        sys.exit(0)

    # Analyse intent of each branch's changes
    intent_a = analyze_intent(diff_a)
    intent_b = analyze_intent(diff_b)

    # Detect semantic conflicts
    conflict_result = detect_conflicts(intent_a, intent_b)

    # Render the report
    generate_report(conflict_result, branch_a, branch_b, intent_a, intent_b)

    # Exit 1 if conflicts were found so CI pipelines can act on it
    if conflict_result.get("conflict_found"):
        sys.exit(1)


if __name__ == "__main__":
    main()

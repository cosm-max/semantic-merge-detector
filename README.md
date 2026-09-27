# Semantic Merge Conflict Detector

> Catch the conflicts git can't — detect when two branches contradict each other's *intent*, not just their lines.

Built for the **IBM Bob Hackathon 2.0**.

---

## The Problem

`git merge` is a text tool. It resolves conflicts line-by-line and is completely blind to what the developer was *trying to do*.

Consider this real scenario from this project's demo:

| Branch | What changed | Why |
|---|---|---|
| `feature/increase-discount` | Discount rate `0.10 → 0.25` | Marketing wants higher discounts to boost sales |
| `feature/lower-threshold` | Minimum order `500 → 200` | Sales wants discounts to apply to more customers |

Git merges both cleanly — **zero merge conflicts**. But the result is that every customer now gets a 25 % discount on orders over $200. Neither team intended the combined effect, no reviewer catches it because nothing looks broken, and no test fails.

This is a **semantic merge conflict**: the code integrates, but the *intent* contradicts.

---

## The Solution

The Semantic Merge Conflict Detector analyses *what each branch is trying to do* and checks whether the two goals contradict each other — before you merge.

```
Branch A diff ──► Intent Analyzer ──► "Adjusts discount rate values"    ──┐
                                                                           ├──► Conflict Detector ──► Rich Report
Branch B diff ──► Intent Analyzer ──► "Adjusts minimum order threshold" ──┘
```

**Pipeline:**

1. **Diff extraction** — each branch is diffed against the common `git merge-base` using `gitpython`
2. **Intent analysis** — heuristic rules classify every changed hunk: value changes, logic inversions, signature changes, renames, additions, deletions
3. **Conflict detection** — six semantic rules compare the two intent sets and fire when they contradict (rate-vs-threshold, concurrent value change, condition-vs-body, and more)
4. **Rich report** — a colour-coded terminal report explains what conflicts were found and what to do about them

No LLM required at runtime. Fully offline. Pure heuristics.

---

## Why IBM Bob

This entire project — architecture, implementation, and debugging — was built using **IBM Bob**, IBM's AI coding partner, in a single session.

### Architect Mode — Reasoning About Design Intent

Bob's **Plan / Ask mode** was used to design the full system before writing a single line of code. The prompt:

> *"I'm building a semantic merge conflict detector… Please create a detailed plan for implementing each file, including what functions each file should have and how they connect to each other."*

Bob produced a structured plan file (`semantic-merge-detector-plan.md`) that:

- Defined the shared `ChangeIntent` and `ConflictResult` data structures **upfront** so all four modules could interoperate without surprises
- Specified every function signature before implementation, establishing a clear contract between modules
- Identified the dependency order (`intent_analyzer` → `conflict_detector` → `report_generator` → `merge_checker`) and correctly flagged that only `merge_checker.py` should interact with git
- Surfaced key design decisions: diff base = merge base (not `main`), cross-file conflict detection scope, and the exit-code contract (`0`/`1`/`2`) for CI pipeline integration

This is precisely the kind of **intent-level reasoning** that separates good architecture from ad-hoc coding — and it mirrors the same capability the tool itself applies to git diffs.

### Agent Mode — Code Generation and Debugging

Once the plan was confirmed, Bob's **Agent mode** implemented each module in sequence, running live validation after each one:

- **`intent_analyzer.py`** — Bob wrote the full unified diff parser, all six heuristic classifiers (`value_change`, `logic_inversion`, `signature_change`, `rename`, `addition`, `deletion`), and the `analyze_intent()` public API, then immediately ran it against the real `demo_repo` diffs to confirm correctness
- **`conflict_detector.py`** — Bob designed a composable, ordered rule-function engine with six semantic conflict rules, ran all five conflict scenarios as smoke tests, and confirmed the no-conflict case returned clean
- **`report_generator.py`** — Bob used Rich's `Panel`, `Columns`, `Table`, `Rule`, and `Text.assemble()` APIs to build the terminal layout, rendering both the conflict and no-conflict paths live during development
- **`merge_checker.py`** — Bob wired the full pipeline, solved the sibling-module `sys.path` import problem for script-mode execution, and added graceful error paths for bad repo paths, unknown branches, and missing shared history

Bob also caught and fixed a real bug mid-session: in `_classify_change()`, the expression `return "addition", f"..." if snippet else "addition", "Added new lines."` was parsed as a **3-tuple** rather than a 2-tuple — a subtle Python comma-expression ambiguity. Bob identified it from the `ValueError: too many values to unpack` traceback and patched it immediately.

### Multi-Step Context Retention

Bob held the full architecture in context across all four implementation steps — checking the exact output shape of one module's dict before writing the next module that consumes it, and always referencing the plan file to stay aligned with the original design. No integration glue was needed after the fact.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       merge_checker.py                           │
│                  CLI entry point · gitpython                     │
│                                                                  │
│  1. Open repo          git.Repo(repo_path)                       │
│  2. Resolve branches   repo.commit(branch_name)                  │
│  3. Find merge base    repo.merge_base(branch_a, branch_b)       │
│  4. Get diffs          repo.git.diff(base.hexsha, branch)        │
└────────────────────────┬─────────────────────┬───────────────────┘
                         │                     │
                         ▼                     ▼
          ┌──────────────────────┐  ┌──────────────────────┐
          │   intent_analyzer    │  │   intent_analyzer    │
          │     Branch A diff    │  │     Branch B diff    │
          │                      │  │                      │
          │  parse_diff()        │  │  parse_diff()        │
          │  _classify_change()  │  │  _classify_change()  │
          │  analyze_intent()    │  │  analyze_intent()    │
          │                      │  │                      │
          │  → intent dict A     │  │  → intent dict B     │
          └──────────┬───────────┘  └──────────┬───────────┘
                     │                         │
                     └────────────┬────────────┘
                                  ▼
                   ┌──────────────────────────┐
                   │     conflict_detector    │
                   │                          │
                   │   detect_conflicts()     │
                   │                          │
                   │   Rules (in priority):   │
                   │   1. signature_change    │
                   │   2. rate vs threshold   │
                   │   3. concurrent value    │
                   │   4. condition vs body   │
                   │   5. add/delete dep.     │
                   │   6. cross-file overlap  │
                   │                          │
                   │   → conflict report dict │
                   └──────────────┬───────────┘
                                  ▼
                   ┌──────────────────────────┐
                   │     report_generator     │
                   │                          │
                   │   generate_report()      │
                   │                          │
                   │   · Header banner        │
                   │   · Branch A panel (blue)│
                   │   · Branch B panel (green│
                   │   · ⚠ Conflict summary   │
                   │   · Per-conflict detail  │
                   │   · Recommendation       │
                   │   · ✔ ALL CLEAR (clean)  │
                   └──────────────────────────┘
```

---

## Tech Stack

| Library | Purpose |
|---|---|
| **Python 3.9+** | Language |
| [gitpython](https://gitpython.readthedocs.io/) | Git repo access and unified diff extraction |
| [click](https://click.palletsprojects.com/) | CLI argument and option parsing |
| [rich](https://rich.readthedocs.io/) | Colour-coded terminal panels, tables, and rules |

---

## Installation

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd semantic-merge-detector

# 2. (Recommended) create a virtual environment
python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

No API keys. No configuration files. Works offline.

---

## Usage

```bash
python3 src/merge_checker.py BRANCH_A BRANCH_B [--repo-path PATH]
```

| Argument / Option | Required | Default | Description |
|---|---|---|---|
| `BRANCH_A` | ✅ | — | First branch to compare |
| `BRANCH_B` | ✅ | — | Second branch to compare |
| `--repo-path` | ➖ | `.` | Path to the local git repository |

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | No semantic conflicts — safe to merge |
| `1` | Semantic conflicts detected — review before merging |
| `2` | Usage error (bad path, unknown branch, no shared history) |

The `1`/`0` contract means the tool can be dropped into a CI pipeline as a pre-merge gate.

---

## Demo Walkthrough

The [`demo_repo/`](demo_repo/) directory contains a small git repository with a realistic pricing conflict scenario.

### Step 1 — The base code

`demo_repo/pricing.py` on `main`:

```python
def get_discount_rate(customer_type):
    rate = 0.10
    if customer_type == "premium":
        rate = 0.15
    return rate

def calculate_discount(order_total, customer_type="regular"):
    minimum_order = 500
    if order_total >= minimum_order:
        rate = get_discount_rate(customer_type)
        return round(order_total * rate, 2)
    return 0
```

### Step 2 — Two independent feature branches

**`feature/increase-discount`** (Marketing team):
```diff
-    rate = 0.10
+    rate = 0.25
-        rate = 0.15
+        rate = 0.30
```

**`feature/lower-threshold`** (Sales team):
```diff
-    minimum_order = 500
+    minimum_order = 200
```

`git merge` sees **no conflict** — the diffs touch different lines.

### Step 3 — Run the detector

```bash
python3 src/merge_checker.py \
  feature/lower-threshold \
  feature/increase-discount \
  --repo-path ./demo_repo
```

### Step 4 — The report

```
──────────────────  SEMANTIC MERGE CONFLICT REPORT  ──────────────────

┌─ feature/lower-threshold ────────────────────────────────────────────┐
│ Intent: Adjusts numeric constants or threshold values                │
│         across 1 function(s) in 1 file(s).                           │
│                                                                      │
│  File         Function           Change Type   Description           │
│  pricing.py   get_discount_rate  Value Change  500 → 200             │
└──────────────────────────────────────────────────────────────────────┘

┌─ feature/increase-discount ──────────────────────────────────────────┐
│ Intent: Adjusts numeric constants or threshold values in 1 file(s).  │
│                                                                      │
│  File         Function  Change Type   Description                    │
│  pricing.py   —         Value Change  0.10 → 0.25, 0.15 → 0.30      │
└──────────────────────────────────────────────────────────────────────┘

⚠  Conflict Summary
  Overall severity:  HIGH
  Conflicts found:   1
  Affected files:    pricing.py

⚠  Conflict 1/1  ·  Concurrent Value Change  ·  HIGH
  Both branches independently changed numeric values in the same
  function 'get_discount_rate'. The changes may contradict each
  other at runtime.

  Recommendation:
  Review both numeric changes together. Decide on a single agreed
  value (or range), implement it in one commit, and discard the
  other branch's change to that constant.
```

**Exit code `1`** — conflicts detected.

---

## Project Structure

```
semantic-merge-detector/
├── src/
│   ├── merge_checker.py     # CLI entry point — git I/O, pipeline wiring
│   ├── intent_analyzer.py   # Unified diff parser, heuristic classifier
│   ├── conflict_detector.py # Semantic conflict rule engine
│   └── report_generator.py  # Rich terminal report renderer
├── demo_repo/               # Sample git repo with pricing conflict scenario
│   └── pricing.py
├── requirements.txt
├── semantic-merge-detector-plan.md  # Architecture plan (created with Bob)
└── README.md
```

---

## What IBM Bob Was Used For

| Phase | Details |
|---|---|
| **System architecture** | Bob produced the full plan file defining data structures, function signatures, module boundaries, and dependency order before any code was written |
| **`intent_analyzer.py`** | Full diff parser, six change classifiers, `analyze_intent()` API, live validation against demo diffs |
| **`conflict_detector.py`** | Composable rule engine with six semantic conflict rules, smoke-tested against synthetic and real data |
| **`report_generator.py`** | Rich terminal layout — conflict and no-conflict paths both rendered live during development |
| **`merge_checker.py`** | Pipeline wiring, `sys.path` import fix, graceful error handling for all failure modes |
| **Debugging** | Caught and fixed a real Python 3-tuple expression bug in `_classify_change()` from a traceback |

---

## Team

| Name | Role |
|---|---|
| *(your name here)* | Developer |

*Built at IBM Bob Hackathon 2.0.*

---

## License

Built as a hackathon demo. Free to use, fork, and extend.

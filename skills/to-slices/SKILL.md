---
name: to-slices
description: >-
  Decompose a plan, PRD, feature description, or existing Linear parent into a VALIDATED DAG of
  vertically-sliced Linear issues — each slice carrying an explicit touch-set, acceptance criteria,
  blocked-by edges, and a layer-rank, ready for the slice-conductor skill to execute in parallel git
  worktrees. Use when the user wants to break a campaign into independently-grabbable slices, turn an
  approved plan into a sliced DAG, prep work for slice-conductor / agent-team execution, or convert a
  bundle into blocked-by/blocks issues. It runs a fail-loud validation gate (Kahn acyclicity +
  antichain collision + layer-rank) so the downstream parallel run can never deadlock or clobber a
  shared file. A customized fork of /to-issues: reach for to-slices for MULTI-SLICE campaigns headed
  for slice-conductor; reach for plain /to-issues for one-off single-issue creation. Trigger with
  "slice this up", "break this plan into issues for the conductor", "make a DAG of this", "prep this
  bundle for slice-conductor", or "decompose this into collision-free slices".
allowed-tools: Read, Write, Edit, Bash, ToolSearch, Skill
---

# to-slices — decompose into a validated slice DAG

## Overview

You turn a plan / feature / bundle into a **`slices.json`** the `slice-conductor` skill executes, and
(after approval) into a Linear parent + sub-issues. Your output is only trustworthy if the DAG is
**provably collision-free and acyclic** — that is the whole point of this skill over plain issue
filing. The conductor runs slices in parallel git worktrees keyed off this DAG, so a missed
shared-file collision clobbers a file and a cycle deadlocks the run. This is a **fork of `/to-issues`**
(tracer-bullet vertical slices); it adds four machine-readable per-slice fields, a validation gate,
and a dry-run/publish split.

Before slicing, it also **captures the converged design into a durable plan doc and hardens it with
`/adversarial-plan-bounce`** — so the front-door (a `/grill-with-docs` convergence or a plan-mode plan)
always lands as one written, adversarially-bounced plan doc, and decomposition never starts from
ephemeral in-chat context. The grilling path otherwise has no adversarial gate; this gives it the same
one plan-mode already has.

## Prerequisites

- The contracts live at `orchestration/contracts/` — `slices.schema.json` is the authority for
  the exact output shape; read it before writing slices.
- The gate runs via `uv run --with jsonschema` (no repo dependency added).
- Pairs with the `slice-conductor` skill, which consumes the `slices.json` you produce.
- Read `references/design.md` for the forking detail, Linear idempotency keys, and a worked example.

## Output

A single `slices.json` at `orchestration/runs/<campaign-slug>/slices.json`, conforming to
`orchestration/contracts/slices.schema.json`. Each slice declares:

- **`touch_set`** — the explicit file/glob paths the slice may modify. The conductor enforces this at
  runtime (`git diff <base>...HEAD` must stay ⊆ this set), so be precise and complete: the module, its
  tests, and any fixture/lockfile the change forces. Write paths consistently across all slices — the
  matcher (`validate_dag._norm`) normalizes a configurable `package_prefix` on both operands so two
  conventions can agree, but mixing forms across slices is a silent-drift hazard. The project's
  package prefix (if any) is supplied via the project-config (see "Layer taxonomy" below).
- **`acceptance_criteria`** — `AC1…ACn`, each one verifiable (for a code slice the `implementer` writes
  the failing test from this text first; for a non-code slice — docs/schema/config/SQL/Linear/research —
  it checks the deliverable against this text with the matching evidence). A verifiable AC is
  **behavior-level, falsifiable, and benefit/contract-anchored** — it names an observable behavior the
  test (or re-run) would FAIL on if removed, never an implementation detail or a vague "works correctly";
  that falsifiability is what gives the `reviewer`'s non-vacuous check teeth.
- **`blocked_by`** — slice ids that must merge before this one starts. Carries BOTH real semantic
  dependencies AND shared-file collision edges.
- **`layer_rank`** (optional, advisory) — the module layer touched (taxonomy below), for display/sanity
  only; NOT a hard gate (vertical slices span layers — Kahn acyclicity is the real cycle guarantee).

## Workflow — the two modes (always dry-run first)

1. **dry-run** (default) — decompose, write `slices.json`, run the validation gate, present the DAG
   for approval. **No Linear writes.** `campaign.approved=false`, `linear_parent_id=null`, every
   `linear_issue_id=null`.
2. **publish** (only after the user approves the dry-run DAG) — create/update the Linear parent + one
   sub-issue per slice **via the Linear MCP** (`list_issues` for find-before-create, `save_issue`,
   `save_comment`, issue relations).
   Set `campaign.approved=true` and fill `linear_parent_id` + each `linear_issue_id`. Linear writes
   happen from THIS skill's main loop only (subagent Linear access silently no-ops to the wrong
   workspace).

Never publish from an unapproved dry-run — a wrong decomposition would create real issues before the
human gate.

Step by step:
1. **Capture the plan doc** (the input-capture seam). If you were handed a plan file (e.g. a plan-mode
   `~/.claude/plans/<x>.md`) or an existing Linear parent, use it as-is — do NOT duplicate it. If you
   were invoked off an in-context `/grill-with-docs` convergence / plan-mode design with **no file**,
   **synthesize the converged design into a plan doc yourself — you, the main loop, never a subagent**:
   the design lives in THIS conversation, so capturing it is synthesis of context you already hold (a
   subagent would only get a lossy copy and add nothing). Write it to
   `orchestration/runs/<campaign-slug>/plan.md` (co-located with the `slices.json` it feeds) and
   show it to the user as a faithfulness check before going further. It must name concrete files/modules
   + acceptance criteria per change — that is what makes the auto-cut DAG good. It must also
   **exhaustively enumerate the behaviors** the campaign delivers — each a verifiable statement that
   becomes ≥1 AC — in whatever framing fits the work: **user-stories** (`As an X, I want Y, so that Z`)
   for user/operator-facing work; **contract / invariant / state-machine-transition** statements for
   infra/refactor/tech-debt. Add an explicit **out-of-scope** list (it seeds the conductor's touch-set boundary).
   This enumeration is the AC source — borrowed from `/to-prd`'s exhaustive-user-story discipline,
   generalized to any project's behavior vocabulary; it's what stops ACs being invented ad-hoc at slice-cut.
   Scale it to the campaign: exhaustive for a substantial one, a short list for a trivial cut.
2. **Harden the plan doc** (the DESIGN bounce). Unless it came pre-bounced from plan-mode AND is
   unchanged, run `/adversarial-plan-bounce` on the plan doc, fold the blockers back in (maximize), and
   show the user the strengthened doc + score. **Never decompose an unbounced plan doc.** Skippable for
   a trivial/obvious decomposition. This asks "is the approach right?" — DISTINCT from the optional
   DAG-edge bounce in step 6 ("is each edge a real dependency, not over-serialization?").
3. Read `references/design.md`.
4. Cut vertical slices (tracer-bullet, per `/to-issues`); assign each its four fields + `shared_core` /
   `maintenance` flags. **Derive the ACs from the plan doc's enumerated behaviors and distribute them** —
   each slice owns a coherent subset. **Coverage check:** every enumerated behavior maps to an AC in
   exactly one slice (none dropped, none duplicated across slices); a slice accumulating too many ACs is
   the signal to split it.
5. Encode shared-file collisions and real dependencies as `blocked_by` edges.
6. Write `slices.json`; run the gate; fix until green. **[optional] DAG-edge bounce** — re-run
   `/adversarial-plan-bounce` on the DAG to check each `blocked_by` is a real dependency, not needless
   over-serialization that kills parallelism; skip on a trivial cut.
7. Present the DAG (slices, edges, the parallel waves the conductor will run) and **ask the user to
   approve**.
8. On approval: publish to Linear idempotently, fill the ids, hand off to `slice-conductor`.

## Layer taxonomy (advisory `layer_rank`) + shared-core

The host project supplies its layer taxonomy, shared-core list, and package prefix via a
**project-config** (`orchestration/project-config.schema.json`). Pass it to `validate_dag.py` with
`--config <file>` or set the `HARNESS_PROJECT_CONFIG` env var. A sample is at
`orchestration/sample-project-config.json`.

Without a config, structural checks (acyclicity, collision) still run; shared-core serialization and
layer-rank validation are disabled with a warning.

Example project-config fields (use whatever layer names match the host project — e.g.
`core/`, `models.ts`, `service.ts`):

```json
{
  "package_prefix": "src/myapp/",
  "layer_ranks": { "core/": 0, "models.ts": 1, "ports.ts": 2, "service.ts": 3 },
  "shared_core_files": ["models.ts", "ports.ts", "core/", "pyproject.toml", "uv.lock"],
  "gate_command": "pnpm test"
}
```

`layer_rank` is **advisory** — the gate does not enforce a rank order (vertical slices legitimately
span layers).

**Shared-core files always get their own single-slice lane.** The gate **derives** `shared_core`
from `touch_set` (set the flag to match, or it fails), and **two concurrent shared-core slices are
a collision** — serialize them with a `blocked_by` edge.

## The validation gate (fail-loud — do NOT hand-wave it)

After writing `slices.json`, run the gate and fix anything it reports before showing the user:

```bash
uv run --with jsonschema python skills/to-slices/scripts/validate_dag.py \
  orchestration/runs/<campaign-slug>/slices.json --mode dry-run
```

It enforces, each a hard stop (exit 1, offending detail printed): schema conformance · well-formedness
(unique ids, blocked_by exist, no self-edge, shared_core matches touch_set) · **mode** (dry-run needs
`approved=false` + null Linear ids) · **acyclicity** (Kahn's — prints the cycle path) · **collision**
(every antichain pair: touch_sets must not overlap by **glob/directory** match — not exact string — and
not both be shared-core; prints the offending paths). A green gate is a precondition for showing the
user the DAG. The conductor re-runs this with `--mode dispatch` (which also requires a published,
approved DAG) before it spawns anything.

The prefix-normalization logic — the single point where the gate's shared-core/collision logic and
the conductor's runtime boundary check must agree — is guarded by a co-located regression test. Run
it whenever you touch `validate_dag.py`'s `_norm`/`paths_overlap`/`is_shared_core`:

```bash
uv run --with jsonschema python skills/to-slices/scripts/test_validate_dag_paths.py
```

(The `--with jsonschema` flag is required even for the test — `validate_dag` imports `jsonschema` at
module load, so importing any of its helpers pulls the dep in.)

`skills/` is not in the host project's pytest/mypy gate, so this test is the only guard on the
matcher — a re-break there would silently flag every code slice as out-of-scope at conductor runtime
(it would merge nothing), so the test exists precisely because that failure mode is invisible until
the run dies at slice 1.

## Error Handling

When the gate fails, do not present the DAG — fix the root cause and re-run:

- **`collision: A and B ... their touch_sets overlap (...)`** (or `... are both shared-core`) — A and B
  can run concurrently but touch the same path (glob/dir-aware) or are both foundational. Fix: add a
  `blocked_by` edge to serialize them, or re-cut so their touch-sets are disjoint.
- **`blocked_by graph has a cycle: A -> B -> A`** — a circular dependency deadlocks the run. Fix: break
  it by extracting the shared concern into its own earlier slice (dependency inversion).
- **`slice X touches a shared-core file but shared_core is not set true`** — set `shared_core=true`.
- **`dry-run must have null linear ids`** / **`dispatch|publish requires campaign.approved=true`** — the
  artifact's mode and its approval/ids disagree; fix the fields or the `--mode`.
- **`schema: ...`** — a field is missing/mistyped vs `slices.schema.json`. Fix the slice to conform.

If a slice's acceptance-criterion wording contradicts the shipped design, leave it for the user — do
not silently rewrite it (that is the conductor's ESCALATE path downstream).

## Examples

**Example — two slices sharing a shared-core file** (`orchestration/contracts/fixtures/slices.example.json`):

Input: a plan with two changes that both touch `models.ts` (S1 = add typed vocab + canary port;
S2 = make `FetchError.reason` required).

Output: S1 `layer_rank 1`, `shared_core true`, `blocked_by []`; S2 `layer_rank 1`, `shared_core true`,
`blocked_by ["S1"]`. Because both touch `models.ts`, they cannot be an antichain, so S2 carries the
serialization edge. Drop that edge and the gate fails loud:
`collision: S1 and S2 can run concurrently but their touch_sets overlap (['models.ts ~ models.ts']) — add a blocked_by edge (serialize) or re-cut`
— exactly the gate doing its job.

See `references/design.md` for the full worked example and the slicing checklist.

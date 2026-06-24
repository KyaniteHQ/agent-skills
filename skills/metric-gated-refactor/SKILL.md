---
name: metric-gated-refactor
description: >-
  Run a metric-gated refactoring loop that curbs fake architecture debt by
  requiring a measured signal (radon cyclomatic complexity + grimp/networkx Louvain
  community detection) AND a named semantic problem before any change — never the
  model's taste. Use when refactoring autonomously, cutting cyclomatic complexity,
  untangling module boundaries, or commissioning a /goal-style overnight refactor
  campaign. Front-loads all decisions in one grill, then GENERATES a ready-to-paste
  /goal prompt that runs the loop until the metrics are clean. Python projects only
  (radon/grimp are Python tools).
---

# metric-gated-refactor

Recurring "improve the architecture" runs fail one way: the model invents
plausible-but-fake debt, "fixes" it, and churns the code. This skill curbs that by
gating every refactor on objective measurement plus a named semantic claim.

## Core principle — a metric is a TRIGGER, not proof

A high number earns a *look*, never a refactor. A candidate is actionable only
when ALL hold:

1. **Objective trigger** — a metric over threshold on *production* code:
   - radon cyclomatic complexity rank ≥ C (CC ≥ 10), or
   - a grimp/networkx Louvain community that crosses package boundaries.
2. **Named semantic problem** — the finding maps to exactly one item of this
   CLOSED list, stated as a one-line falsifiable claim citing source lines:
   `duplicated decision logic · unstable boundary · hard-to-test branch ·
   config-wiring sprawl · violated repo invariant`.
3. **Louvain only** — a concrete boundary claim: "module A imports B for reason
   X that belongs behind port Y." No claim → no refactor. The project's
   composition root (if one exists) is EXEMPT — wiring every adapter is its job.

"This feels shallow" is not a candidate. A number with no named problem is dropped.

## Anti-gaming invariants (a refactor that games the metric is reverted)

- No call-only wrapper extraction (a pass-through that only relocates a call).
- No single-use abstraction unless it names an existing `CONTEXT.md` domain concept.
- No moving branches into a private helper just to lower per-function radon.
- Tests prove behaviour, not the extracted shape.
- **Improve-or-revert, bounded** — after the refactor, re-measure and keep it only if:
  - the target function's MAX CC dropped by the agreed delta (bounded — e.g.
    `38 → ≤25` on the first pass, not `<10` in one leap), AND
  - no NEW rank-C+ helper appeared, AND
  - total CC across the touched production files did not increase, AND
  - the full offline gate is green and coupling (Louvain) is no worse.

  Otherwise `git revert` the step. Total CC need not always fall — legitimate
  decomposition can hold it level while max CC drops.

## Phase A — front-load grill (interactive, once)

Run with the user present, grill-with-docs style (one question at a time, each with
a recommended answer; explore code instead of asking where you can). Read
`CONTEXT.md`, `docs/DECISIONS.md`, `AGENTS.md`, `CLAUDE.md`, and `.claude/rules/*.md`
first. Lock the campaign config:

- Scope + hard exclusions (frozen files or packages; never edit `pyproject.toml`/`uv.lock`;
  any project-specific no-change rules supplied by the owner).
- Thresholds (default radon rank ≥ C; Louvain boundary-claim required).
- Stop condition (K consecutive dry rounds, default 2, + per-run step budget).
- The optional smoke/canary surface list, plus the landing and issue-tracker policies in
  `references/loop-spec.md`.

**Then GENERATE the run prompt** — fill the placeholders in
`assets/goal-run.template.md` with the locked config (scope, thresholds, K, step
budget, the optional canary surface list) and **write the concrete prompt to**
`.claude/prompts/refactor-goal-run.md` (overwritten per campaign). End by telling the
user the single command that starts the AFK run:

```
/goal .claude/prompts/refactor-goal-run.md
```

The planning session does NOT run the loop itself.

## Phase B — autonomous loop

The full algorithm is `references/loop-spec.md`. It runs only when the user launches
the generated prompt via `/goal`, and STOPS before merging to `main` (it prepares
the PR; merging is a separate go-ahead). Metric commands and the Louvain script are
in `references/metrics.md`.

## Non-negotiables

- Metrics run ephemerally via `uvx` — never added to `pyproject.toml`/`uv.lock`.
- Optional smoke/canary command is conditional, not per-step, and does not replace the
  offline gate — see `references/loop-spec.md`.
- All issue-tracker writes from the orchestrator main loop only (subagents report-only).
- Never write `MEMORY.md` or the memory dir from the loop — owner-controlled surface.
- Respect the invariants in any project-local `.claude/rules/*.md` files.

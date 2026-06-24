# to-slices — design notes

Detail kept out of the always-loaded SKILL.md body. Read this when actually running a decomposition.

## Relationship to /to-issues and slice-conductor

- **Forked from `/to-issues`.** The vertical-slicing philosophy (each slice a thin end-to-end
  tracer bullet that independently delivers value, not a horizontal layer) is unchanged — reuse it.
  What this fork adds: the four machine-readable per-slice fields (`touch_set`, `acceptance_criteria`,
  `blocked_by`, `layer_rank`), the `validate_dag.py` gate, and the dry-run/publish split. `/to-issues`
  emits prose issues; `to-slices` emits a `slices.json` a program consumes.
- **Pairs with `slice-conductor`.** That skill reads this `slices.json`, creates a git worktree per
  slice, dispatches a persistent `implementer` teammate + a `reviewer` per slice (defined at
  `agents/implementer.md` + `agents/reviewer.md`), runs them to PASS, and ships in DAG order via
  `babysit-pr`. So every field here is consumed downstream: `touch_set` becomes the runtime boundary
  check, `blocked_by` becomes the parallel schedule, `acceptance_criteria` becomes the implementer's
  failing tests + the conductor's AC gate.

## Why the gate is non-negotiable

The conductor runs the DAG's ready-frontier in parallel worktrees. Two failure modes the gate
prevents:
- **Collision** — two slices that can run at the same time (a DAG antichain) both edit the same file.
  In separate worktrees their commits diverge and the second merge clobbers the first. The gate
  asserts every antichain pair has disjoint `touch_set`s; the fix is a serialization `blocked_by`
  edge or a re-cut.
- **Cycle** — `A blocked_by B`, `B blocked_by A`: neither ever becomes eligible, the run deadlocks.
  Kahn's algorithm catches it and prints the cycle so it can be broken (extract the shared piece into
  its own earlier slice — dependency inversion).

The agent-teams platform does NOT isolate teammates automatically (the conductor makes worktrees by
hand) and its docs explicitly say "avoid file conflicts — break work so each owns different files."
So the disjoint-touch-set DAG IS the conflict-avoidance mechanism the platform assumes — the gate is
what makes that guarantee real instead of hoped-for.

## Publish mode — Linear idempotency

Publish only after the user approves the dry-run DAG. Make every write idempotent so a re-run (or a
resumed conductor) never double-files:

| Entity | find-before-create key |
| --- | --- |
| parent | the campaign `slug` (search open issues for the parent title + a `bundle:<slug>` label) |
| child | the slice `id` (search children of the parent whose title carries `[<id>]`) |
| edge | the `<from>-><to>` pair (a Linear blocks/blocked-by relation; check before adding) |
| AC checkbox | the AC text checksum (don't reorder/duplicate existing checkboxes) |

Implement these via the **Linear MCP**: `list_issues` (filtered by the parent + a `bundle:<slug>` label)
for find-before-create, `save_issue` for create/update, `save_comment` for AC evidence, and the
issue-relation API for blocks/blocked-by edges. Tag the parent + children with a `bundle:<slug>` label so
the conductor and a re-run can find them. All Linear writes happen from this skill's main loop — never
delegate them to a subagent (subagent Linear access resolves to the wrong workspace and silently no-ops).

## Worked example — two slices sharing a shared-core file

The fixture `orchestration/contracts/fixtures/slices.example.json` is a two-slice cut:

- **S1** (add typed vocab + canary port) touches `models.ts`, `ports.ts`, `service.ts`, … →
  `layer_rank 1`, `shared_core true`, `blocked_by []`.
- **S2** (make `FetchError.reason` required) touches `models.ts`, the fetchers, … → `layer_rank 1`,
  `shared_core true`, `blocked_by ["S1"]`.

Both touch `models.ts`, so they are NOT disjoint → they cannot be an antichain → S2 carries the
serialization edge `blocked_by ["S1"]`. Drop that edge and `validate_dag.py` fails loud:
`collision: S1 and S2 can run concurrently but their touch_sets overlap (['models.ts ~ models.ts'])`.
That is the gate doing its job.

## Slicing checklist

For each slice, before writing it:
- Is it a thin vertical tracer bullet (delivers a verifiable behavior end-to-end), not a horizontal
  layer?
- Is its `touch_set` complete (module + tests + any forced fixture/lockfile)?
- Does any other slice in its wave touch an overlapping path? If yes → edge or re-cut.
- Does it touch a shared-core file? If yes → `shared_core true` + its own serial lane.
- Is each AC a single, test-able behavior?
- Do its `blocked_by` edges all point to a lower-or-equal `layer_rank`?

Then run `validate_dag.py` and let it prove the whole graph.

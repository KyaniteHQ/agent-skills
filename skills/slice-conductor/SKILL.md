---
name: slice-conductor
description: >-
  Execute a validated slice DAG (a to-slices `slices.json`) end-to-end as the team lead of an agent
  team: create a git worktree per slice, dispatch a PERSISTENT implementer teammate + a reviewer per
  slice, run the implement->review->fix loop to PASS (keeping the same implementer alive across review
  rounds via SendMessage), gate acceptance criteria in the main loop, own every Linear write, merge
  each green slice into a campaign integration branch behind a light shift-left gate, then ship the
  whole branch to main via one babysit-pr. Use when the user wants to run/execute a slice bundle,
  drive a campaign of slices to merged, "run the conductor", "execute the DAG", "build out these
  slices in parallel", or take a to-slices/slices.json from approved to shipped. It maximizes
  parallelism by the DAG's ready-frontier (capped at 5 in-flight slices) while honoring the hard
  constraints (Linear-writes-from-the-lead-only, manual worktrees, runtime touch-set boundary checks,
  shared-core serialization, ESCALATE-to-owner). Pairs with to-slices (which produces the DAG).
  Trigger with "run slice-conductor", "execute this slices.json", "drive these slices to merged",
  "conduct the campaign", or "build the bundle in parallel worktrees".
allowed-tools: Read, Write, Edit, Bash, Agent, SendMessage, TaskList, AskUserQuestion, ToolSearch, Skill
---

# slice-conductor — run a slice DAG as an agent-team lead

## Overview

You are the **team lead**. You take an approved `slices.json` (from `to-slices`) and drive the whole
campaign onto `main` as **one squashed commit**: each green slice merges into a campaign **integration
branch** behind a **light gate** (in-team review + AC gate + boundary check + a local Greptile pass),
and when every slice is in, the **whole branch ships to `main` via one `babysit-pr`** (the heavy gate:
six CI gates + Greptile-to-5/5 + check-pr). The DAG's ready-frontier runs in parallel git worktrees
while a single **run ledger** holds the durable machine state. Each slice gets a persistent
`implementer` teammate and a `reviewer`; the implementer stays alive across review rounds so it fixes
with full context. You — never a teammate — own all Linear writes, the acceptance-criteria gate, the
integration merges, and the final ship. The per-slice state machine is in `references/loop.md`
(the 80/20 split is §5); the exact teammate spawn prompts are in `references/dispatch-prompts.md`. Read
both before running.

## Prerequisites

- **Agent teams enabled.** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` must be set (it is, in
  `~/.claude/settings.json`). Confirm a live team dir exists: `ls -d ~/.claude/teams/session-*/`.
  **Fail closed** with a clear message if absent — the whole substrate depends on it.
- **Clean team roster (the runaway guard).** Before dispatching anything, enumerate the live team
  members (`TaskList`, or the member files under `~/.claude/teams/session-*/`). The ONLY permitted live
  members are the lead and prior `impl-<id>` / `rev-<id>` teammates (type `implementer` / `reviewer`).
  If ANY other member is alive — above all a **`general-purpose`** one, which holds the Agent tool and
  self-spawned a 120+-agent, ~$242 runaway — **fail closed**: shut it down (SendMessage
  shutdown_request) and re-check before proceeding. A stray general-purpose teammate inherited from a
  prior task is exactly the hole this preflight closes; never run the conductor over a dirty roster.
- **An approved, PUBLISHED DAG.** Re-run the gate in dispatch mode — it **fails closed** unless
  `campaign.approved == true` AND the DAG is published (non-null `linear_parent_id` + every
  `linear_issue_id`, so the Linear lifecycle is satisfiable):
  `uv run --with jsonschema python to-slices/scripts/validate_dag.py <slices.json> --mode dispatch`
  (pass `--config <orchestration/project-config.json>` or set `HARNESS_PROJECT_CONFIG`).
  A wrong/unapproved decomposition must not spawn agents.
- **Run in a permission mode that lets teammates Edit/Write/commit** — teammates inherit the lead's
  mode at spawn (they don't get the subagent's `permissionMode`).
- The `implementer` + `reviewer` agents (at `agents/implementer.md` + `agents/reviewer.md`), the
  `babysit-pr` skill, and `tdd` skill exist.
- Read `orchestration/agent-teams-notes.md` — the platform quirks + the **never-spawn-`general-purpose`** safety rule this skill is built around.

## Output

- The whole campaign **squash-merged to `main` as ONE commit** via a single `babysit-pr` PR from the
  campaign **integration branch** (`integration/<slug>`). Each slice merges into that branch behind the
  light gate (loop.md §5a); the integration branch is created once off synced `main` and **deleted after
  the squash to `main`** (loop.md §5b). No per-slice PR-to-main.
- A **run ledger** at `orchestration/runs/<slug>/ledger.json` (the `run-ledger` contract: a
  `{campaign_slug, slices:[...]}` object whose `slices` are `ledger-entry` records — the exact shape
  `frontier.py` reads), updated at every transition — the conductor's durable **machine state** for
  scheduling + `/resume` (distinct from Linear, which is the human-facing record).
- **Linear kept current at every transition** from the main loop — the durable, human-facing source of
  truth, **never stale**: In Progress on dispatch, a body status line each review round, AC checkboxes
  ticked with redacted evidence on gate-pass, "merged into integration" in the body on integrate, Blocked
  on escalation, and **Done (every child + the parent) with branch/SHA only at the campaign ship to
  `main`** (Done stays honest — integration is not main). Body-current (not a comment trail); comments
  reserved for durable findings. Full per-transition map + the single-writer rule: `references/loop.md` §4.
  The owner reads Linear to know the true state of the campaign.

## The run loop (high level)

Repeat until `frontier.py` reports `complete`:

1. **Preflight** (once): prereq checks above — including the **clean-roster check** (no stray
   `general-purpose` teammate); load or create the ledger; and **cut the campaign integration branch**
   off synced `main` — `integration/<slug>` (loop.md §0), recorded in the ledger's `integration_branch`.
2. **Schedule**: `uv run python slice-conductor/scripts/frontier.py <slices.json>
   <ledger.json>` -> the **launch set** (eligible ∩ remaining ceiling slots; `persistent_teammates`
   echoes the live-implementer count). `stuck` -> ESCALATE.
3. **Dispatch** each launch slice: **base off the integration tip** — `base_sha=$(git rev-parse
   integration/<slug>)` (no per-dispatch `main` sync — §0 synced once; the integration branch already
   contains every `merged` dependency); `git worktree add worktrees/<id> -b slice/<id>
   $base_sha`; record `base_sha`; spawn a named `impl-<id>` teammate via the **Agent tool**
   (`subagent_type: implementer`, `name: impl-<id>`, `run_in_background: true` — **never
   `general-purpose`**) with the dispatch prompt. Ledger phase -> `dispatched`; record `agent_id`; **set
   Linear In Progress + a body status line (§4).**
4. **Review loop** (per slice, `references/loop.md`): on the implementer's idle, **run the boundary
   check** (catch cwd-bleed early) and read its report file (record `report_file`/`files_changed`) ->
   spawn `rev-<id>` (`reviewer`), read its verdict, **tear `rev-<id>` down** (stateless across
   rounds; keeps the live-teammate count at the ceiling) -> on `CHANGES`, record `last_defects`, **update
   the Linear body status line for the round (§4)**, then the LEAD SendMessages the defects to the LIVE
   `impl-<id>` (context kept), bump `round_count`; loop **≤3 rounds**, else ESCALATE.
5. **Main-loop AC gate + boundary check**: confirm the evidence, and run the boundary check —
   `uv run --with jsonschema python scripts/boundary_check.py --config <orchestration/project-config.json> <slices.json> <id> <worktree> <base_sha>`
   (the `--with jsonschema` is required — it imports `validate_dag`; full command in loop.md §3) —
   committed + untracked ⊆ `touch_set`, via the gate's matcher. A breach -> ledger `blocked` + Linear
   `Blocked` (§4), do NOT merge. Pass -> ledger `pass` + **tick the Linear AC checkboxes with redacted evidence (§4)**.
6. **Integrate** (per slice, on the one batch 'go'; `references/loop.md` §5a): when a slice is `pass` AND
   all its `blocked_by` are `merged`, run the **light gate** — a local `greptile review` on top of the
   already-green in-team review + AC gate + boundary check (skip Greptile for `maintenance`) — then
   `git checkout integration/<slug> && git merge --no-ff slice/<id>` (local, never `main`); `git worktree
   remove worktrees/<id>` + `git branch -d slice/<id>`; shut down its `impl-<id>`. Ledger `merged`
   (= into integration); Linear body "merged into integration" (status stays In Progress, §4).

When `frontier.py` reports `complete` (every slice merged into integration), do the **campaign ship once**
(`references/loop.md` §5b): run the full offline gate on the integration branch, then **one `babysit-pr`
integration→`main`** (the heavy gate — six CI gates + Greptile-to-5/5 + check-pr) squash-merges the whole
campaign as one commit; re-sync local `main`, **delete the integration branch**, record `campaign_pr` +
`campaign_merge_sha`, and set every child + the parent to Linear **Done** (§4). Once `campaign_merge_sha`
is recorded the campaign is done — **stop** (frontier keeps reporting `complete`, so the recorded sha is
the ship-once guard; never re-enter §5b once it is set).

Update the ledger after every step so a `/resume` (which kills teammates) can pick up by re-spawning
implementers for non-`merged` slices from the ledger + a context packet, and re-establishing the
integration branch.

## Hard constraints (violations are defects)

- **Linear writes from the lead's main loop ONLY, and kept current at every transition (never stale)** —
  Linear is the durable human source of truth; the lead is the single writer. Teammates are report-only
  (their `linear-server` writes silently no-op to the wrong workspace), so the lead transcribes their
  redacted evidence. Body-current (project-config secret identifiers only — never the project's raw
  secrets/PII); comments for durable findings, not a status trail. Per-transition map:
  `references/loop.md` §4.
- **You create worktrees manually** — the Agent `isolation:"worktree"` flag is a no-op for main-loop
  teammates (they run in the main tree). No worktree -> cwd-bleed.
- **Teammates never push or merge** — they commit on their worktree branch; the LEAD merges each green
  slice into the **integration branch** (§5a). Slices NEVER merge into `main`; the only `main` merge is
  the single campaign-level integration→`main` `babysit-pr` (§5b). The integration branch is the
  campaign trunk — cut once off synced `main`, slices base off it and merge into it, deleted after the
  squash to `main`.
- **Boundary check after every teammate turn** — committed diff ⊆ `touch_set`, else `blocked`.
- **Shared-core / dependency slices run serially** — the DAG already serializes them via edges; never
  override the schedule to run two `shared_core` slices at once.
- **No nested teams; NEVER `general-purpose`.** Spawn `impl-`/`rev-` only as `implementer` /
  `reviewer` (no Agent tool -> they can't self-spawn; a `general-purpose` teammate self-spawned into
  a 120+-agent runaway, ~$242). The **lead routes every CHANGES packet and owns the ledger** — the
  reviewer writes its verdict only and does NOT message the implementer directly (unledgered rounds).
- **`/tdd` must be named in the spawn prompt** — the subagent's `skills:` frontmatter is NOT applied to
  a teammate.
- **Live/network runs are the lead's attended job** — never delegate them to a teammate; they require
  the project's secrets/PII and attended oversight.
- **ESCALATE goes to the owner** — AC-text drift, >3 rounds, a boundary breach, or a `stuck` DAG:
  surface it via AskUserQuestion and hold that slice; keep running the rest of the frontier.

## Error Handling

- **Prereq missing** (no team dir / `approved=false` / DAG invalid): stop with the exact reason; do not
  spawn anything.
- **Reviewer `CHANGES` x3 or `ESCALATE`**: ledger `held`; surface the defects/mismatch to the owner; do not
  merge.
- **Boundary breach** (diff exceeds `touch_set`): ledger `blocked`; show the offending paths; ask the
  owner whether to widen the touch_set or re-cut.
- **`frontier.py` reports `stuck`**: held/blocked slices are gating progress -> ESCALATE to the owner.
- **Un-hold after the owner resolves**: a `held`/`blocked` slice stays out of `frontier.py`'s schedule
  until you clear it. Once the owner decides (fix the AC text, widen the touch_set, re-cut),
  re-dispatch that slice — re-spawn its `impl-<id>` with the resolution folded into the context packet
  (same mechanic as the `/resume` re-spawn, §6) and set its ledger `phase` back to `dispatched`.
- **Resume after `/resume`**: teammates are gone; for every non-`merged` slice re-spawn its implementer
  with a context packet (prior diff + last reviewer findings from the ledger). Never SendMessage a
  teammate the ledger doesn't list as live this session.
- **Task board disagrees with the ledger**: trust the ledger + reviewer verdict + boundary check (the
  agent-teams task status is known to lag).

## Examples

**Example — run the architecture-deepening bundle** (`slices.json` from `to-slices`: ISSUE-S1 then
ISSUE-S2, both `shared_core`, `S2 blocked_by S1`):

1. Preflight passes; cut `integration/arch-deepening-2026-06` off synced `main`; `frontier.py` ->
   `launch: ["S1"]` (S2 blocked).
2. `base_sha=$(git rev-parse integration/arch-deepening-2026-06); git worktree add worktrees/S1
   -b slice/S1 $base_sha`; spawn `impl-S1` (`subagent_type: implementer`); it TDDs
   `models.ts`/`interfaces.ts`/`service.ts` (the project-config's `shared_core` list), writes its
   report file, replies via SendMessage.
3. `rev-S1` PASS; AC gate + boundary check (diff ⊆ S1.touch_set) pass; ledger `pass`. Light gate: local
   `greptile review` -> clean. Merge into integration (`git merge --no-ff slice/S1`); remove worktree +
   `slice/S1`; shut down `impl-S1`; ledger `merged`; Linear body "merged into integration" (still In
   Progress).
4. `frontier.py` -> `launch: ["S2"]` (its blocker is merged into integration); S2 branches off the new
   integration tip; same loop -> ledger `merged`. `frontier.py` -> `complete`.
5. **Campaign ship (once):** full offline gate on the integration branch is green -> one `babysit-pr`
   integration→`main` (six CI gates + Greptile-to-5/5 + check-pr) squash-merges the campaign as **one
   commit**; re-sync `main`, delete `integration/arch-deepening-2026-06`; S1, S2, **and the parent** ->
   Linear `Done` with the `main` merge SHA.

See `references/loop.md` for the full state machine and `references/dispatch-prompts.md` for the exact
teammate prompts.

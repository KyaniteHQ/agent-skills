# slice-conductor — the per-slice state machine

The detailed algorithm behind the SKILL.md run loop. The ledger
(`.claude/orchestration/runs/<slug>/ledger.json`, a `run-ledger` object `{campaign_slug, slices:[ledger-entry...]}` — the shape `frontier.py` reads) is the durable
truth — update it after EVERY transition so a `/resume` can reconstruct the run.

## Phases

This conductor uses a campaign **integration branch**. Slices merge **into it** (never into `main`)
behind a **light per-slice gate** — the 80/20: the in-team `reviewer` + the AC gate + the boundary
check + a local `greptile review` (CLI, shift-left). The **heavy** review — `babysit-pr` (the six CI
gates + Greptile-to-5/5 + check-pr) — runs **ONCE**, when the whole integration branch ships to `main`
as a **single squashed commit**. Per-slice review is cheap and local; the hardest review is at the
integration→main boundary.

```
pending ─dispatch─► dispatched ─PASS + AC gate + boundary─► pass ─light gate + merge into integ─► merged
                        ▲   │
                        │   └─reviewer CHANGES (SendMessage to live impl)─► (round_count++, ≤3)
                        └─────────────────────────────────────────────────┘
ALL slices merged ─► campaign ship: babysit-pr integration→main (squash) ─► children + parent Done
held    = ESCALATE (AC drift, >3 rounds) — awaiting the owner
blocked = boundary breach / unrecoverable — awaiting the owner
```

`merged` means **merged into the integration branch** — that is what satisfies a dependent's
`blocked_by` and unblocks it (dependents branch off the updated integration tip). `dispatched|changes|
pass` are in-flight (occupy a ceiling slot). `held|blocked` need the owner and do NOT occupy a slot.
`shipped` is unused per-slice here — the only "ship" is the campaign-level integration→main.

## 0. Campaign start (once)

Sync local `main` to the remote, then cut the campaign **integration branch** off it:
`git fetch origin && git checkout main && git merge --ff-only origin/main && git checkout -b
integration/<campaign-slug>`. Record it in the ledger top-level `integration_branch`. Cut off the
**local** `main` you just fast-forwarded — do NOT pass `origin/main` as the start-point: that would
drop any local-only `main` commits and set the branch's upstream to `origin/main`, wedging a later bare
`git push`. This
is the **only** sync of `main` until the campaign ships — slices branch off and merge into integration
**locally**, so `main` cannot go stale mid-campaign (there is no per-slice remote merge). The branch is
pushed to `origin` only when `babysit-pr` needs it for the final PR (§5b).

## 1. Dispatch

For each id in `frontier.py`'s `launch` set:

1. **Base off the integration tip.** A slice becomes eligible only once its `blocked_by` are `merged`
   (= merged into integration), so the current integration tip already contains every dependency. Record
   `base_sha = git rev-parse integration/<campaign-slug>`. (No `main` sync here — §0 synced once; the
   integration branch is the campaign's working trunk, and the boundary check still diffs
   `base_sha...HEAD`.)
2. **Create the worktree** (the `isolation` flag is a no-op — do it by hand):
   `git worktree add .claude/worktrees/<id> -b slice/<id> <base_sha>`. Record `worktree_path`, `branch`.
3. **Spawn the implementer** — a named, backgrounded teammate via the Agent tool
   (`subagent_type: implementer`, never `general-purpose`), using the prompt in
   `dispatch-prompts.md`. Record its `agent_id` (for SendMessage re-entry). First `mkdir -p` the
   main-tree `orchestration/runs/<slug>/reports/` dir and fill `<report_file>` (and later
   `<verdict_file>`) as ABSOLUTE paths under it — a relative path resolves against the teammate's
   worktree cwd, where the lead can't read it (see `dispatch-prompts.md`).
4. Ledger: `phase=dispatched`, `round_count=0`, stamp `updated_at`.

Respect the ceiling: never dispatch more than `ceiling - in_flight` at once (frontier already caps the
`launch` list, but re-check before each spawn). Never dispatch two `shared_core` slices concurrently —
the DAG edges already prevent this; if you ever see it, the DAG was mis-validated, stop.

## 2. Review loop (per slice)

1. **Implementer idle** -> FIRST run the boundary check (§3 below) to catch cwd-bleed early, then read
   its **report file** (the reliable channel; the SendMessage reply is a convenience, the file is
   truth). If it reports `linear_state_set=ESCALATE`, go to **held**.
2. **Spawn the reviewer** `rev-<id>` (`subagent_type: reviewer`) against the branch + commit + the
   slice's ACs + its `base_sha` (so it diffs `base_sha...HEAD` — this slice's own changes — not `main`;
   prompt in `dispatch-prompts.md`). Read its verdict file; record `verdict_file` in the ledger. **Then shut `rev-<id>` down immediately** (SendMessage shutdown_request). The reviewer is
   stateless across rounds — a fresh one is spawned each round — so leaving it alive only burns a
   teammate slot. This is what keeps the live teammate count ≈ the ceiling of persistent implementers
   (frontier's `persistent_teammates`) instead of growing 2x; only `impl-<id>` persists between rounds.
3. **Branch on the verdict:**
   - `PASS` -> ledger `last_defects=[]`; go to the AC gate (step 3).
   - `CHANGES` -> ledger `last_defects=<the verdict's defects>` (so a `/resume` can replay them — the
     reviewer is already gone), then SendMessage the defects to the **live `impl-<id>`** (context
     intact — do NOT spawn a fresh implementer); `round_count++`. If `round_count > 3` -> **held**
     (don't loop forever). Else wait for the implementer's next idle and re-review (spawn a fresh
     `rev-<id>`).
   - `ESCALATE` -> **held**.

The implementer and reviewer are both lead-spawned (no nested teams; never `general-purpose`). The
reviewer writes its verdict ONLY — the LEAD sends every CHANGES packet to the implementer and updates
the ledger first; no direct rev->impl messaging (it would create unledgered rounds).

## 3. AC gate + boundary check (main loop, before any merge)

1. **AC gate:** re-read the implementer's `acs_ticked` + `at_result` + `full_suite` and the reviewer's
   `ac_check`. Every in-scope AC must be `met` with non-vacuous evidence and the suite green. If not ->
   treat as `CHANGES` (back to step 2) or `held`.
2. **Boundary check** (the cwd-bleed / scope guard — the ONLY allowed source of `boundary_ok`, run it
   after every implementer turn AND before any merge):
   ```bash
   uv run --with jsonschema python slice-conductor/scripts/boundary_check.py \
     --config <orchestration/project-config.json> \
     <slices.json> <id> worktrees/<id> <base_sha>
   ```
   Pass `--config` (or set `HARNESS_PROJECT_CONFIG`) so the script reads the project's shared_core
   list and touch_set semantics. It gathers committed-since-`base_sha` + untracked paths and checks
   each against the slice's `touch_set` with the **same `paths_overlap` matcher as the gate** (so
   glob/dir semantics can't drift) — exit 1 and an `out_of_scope` list on breach. Any out-of-scope
   path (a stray edit, an undeclared lockfile, a regenerated config artifact) -> ledger `blocked`,
   surface the paths to the owner (widen the touch_set or re-cut). Do NOT merge.
3. Pass both -> ledger `phase=pass`, store `head_sha`, `ac_evidence` (redacted: `case_id`/`*_hash`
   only), `boundary_ok=true`.

## 4. Linear — the durable, human-facing source of truth (lead only, never stale)

Linear is what the owner (and any future session) reads to know the true state, so the lead keeps it
**current at EVERY transition**, not just at the end. Division of record: the **ledger** is the
machine's resume/scheduling state; **Linear** is the record of record for humans. The lead is the
**single writer** — teammates are report-only (their `linear-server` writes silently no-op to the wrong
workspace), so the lead transcribes their **redacted** report evidence into Linear. Keep the issue
**BODY (description) current** (state reads true at a glance) and reserve **COMMENTS** for durable
findings/decisions/escalation, never a mechanical status trail.

Every write is a `linear-write` op from the main loop, idempotent via `comment_marker` + `ac_checksum`
(so a re-run or `/resume` updates in place, never duplicates). Redacted throughout — project-config
secret identifiers only, never raw project secrets/PII:

| transition | op(s) | effect |
| --- | --- | --- |
| dispatch | `set_status` + `update_body` | child -> **In Progress**; body status line: "in build — branch `slice/<id>`, round 0/3" |
| each review verdict | `update_body` | body: "round N/3 — reviewer PASS" / "round N/3 — reviewer CHANGES: `<one-line>`" |
| AC gate pass | `tick_ac` (per AC) | tick each AC checkbox in the body with its redacted evidence |
| merged into integration | `update_body` | body: "merged into `integration/<slug>` — awaiting campaign ship to main". **Status stays In Progress** — Done means *on main*, and integration is not main yet. |
| held / blocked | `set_status` + `comment` | child -> **Blocked**; a durable comment with the escalation / boundary-breach detail |
| campaign ship (integration→main) | `set_done` (each child + the parent) | every child issue **and** the parent -> **Done** with branch + the `main` merge SHA. **Never Done before the squash to main is confirmed.** |

The body carries CURRENT state (checkboxes + one status line you overwrite each step); comments carry
WHY (findings, decisions, escalation context). A slice's deliverable is in integration but NOT shipped
until the campaign squashes to `main`, so its issue stays In Progress (body shows "integrated") and
flips to Done only at the campaign ship — Done stays honest. The lead writes Linear AND the ledger on
the same transition, so the two never diverge. Never delegate any Linear write to a teammate.

## 5. Integrate (per slice) + ship (campaign)

### 5a. Integrate a slice into the integration branch (the light 80/20 gate)

A slice integrates when `phase=pass` AND every `blocked_by` slice is `merged` (already true — that is how
it became eligible). Run the **light gate**, then merge it into integration:

1. **Light gate** (cheap, local, no GitHub PR — the 20% that catches ~80%):
   - the in-team `reviewer` PASS + the main-loop AC gate + the boundary check are already green (§2/§3);
   - the offline suite is green (the implementer + reviewer ran it);
   - **local Greptile shift-left** — `greptile review -b integration/<slug>` from the worktree (the
     `/greptile-cli` skill). On findings, route them to the live `impl-<id>` as a CHANGES round (≤3,
     ledgered) and re-run. **Skip this for a `maintenance`-tagged slice** (trivial — in-team review
     suffices); the heavy integration→main gate still covers it.
2. **Merge into integration** (local — never a remote push, never `main`):
   `git checkout integration/<slug> && git merge --no-ff slice/<id> -m "integrate <id>"`. Concurrent
   slices have disjoint touch_sets (the DAG guarantees it), so this never conflicts; a conflict means the
   DAG was mis-cut -> **`git merge --abort`** (leave integration clean so the other slices can still
   integrate), then ledger `held` and surface to the owner. Integration's internal merge commits never
   reach `main` — §5b squashes the whole branch into one commit.
3. **Cleanup + ledger:** `git worktree remove worktrees/<id>` + `git branch -d slice/<id>`; shut
   down `impl-<id>` (`rev-<id>` was torn down in §2). Ledger `phase=merged`, `merge_sha = the
   integration-merge commit`, `ship_pr=null` (there is no per-slice PR). Linear: body "merged into
   integration" (§4 — status stays In Progress).

Then re-run `frontier.py` — a slice reaching `merged` may unblock dependents (they branch off the new
integration tip).

### 5b. Ship the campaign to main (the heavy gate — ONCE, on the batch 'go')

When `frontier.py` reports `complete` (every slice `merged` into integration):

1. **Whole-branch gate:** run the project's full offline gate command (project-config `gate_command`,
   or the project's AGENTS.md/CLAUDE.md) on the integration branch — the slices were gated
   individually; this proves they compose.
2. **`babysit-pr` integration→main** (the hardest review, run once): push `integration/<slug>` to
   `origin`, hand it to `babysit-pr`, which opens the PR (integration → `main`), drives the **six CI
   gates** + the **Greptile-to-5/5 loop** + the **check-pr breadth sweep**, and **squash-merges** — so
   the whole campaign lands as **one commit on `main`**. Record `campaign_pr`.
3. **On merge confirmed:** re-sync local `main` (`git fetch origin && git checkout main && git merge
   --ff-only origin/main`); record `campaign_merge_sha`. **Delete the integration branch** now that it
   has no further use: `git branch -D integration/<slug>` (local). The REMOTE branch was almost
   certainly already deleted by `babysit-pr`'s `gh pr merge --squash --delete-branch`, so run the remote
   delete only if it still exists and don't fail on a missing ref:
   `git push origin --delete integration/<slug> || true`.
4. **Linear Done:** set every child issue **and** the parent to **Done** with branch + `campaign_merge_sha`
   (§4) — the first moment any of them is truly on `main`.

Once `campaign_merge_sha` is recorded the campaign is **complete — stop**. `frontier.py` keeps
reporting `complete` (slices stay `merged`), so the recorded sha is the idempotency guard: never
re-enter §5b once it is set (§6.4 only resumes §5b when it is still null).

The batch 'go' is one consent from the owner covering the per-slice integrations AND the final
integration→main squash-merge. Stop for a fresh confirm on any ESCALATE, gate failure, or boundary
breach. The owner can cancel/hold the remaining frontier (or the final ship) at any barrier.

## 6. Resume (after `/resume` — teammates are gone)

`/resume` does not restore in-process teammates (the integration branch + worktrees survive on disk).
On resume:
1. Load the ledger. Re-establish the integration branch from the top-level `integration_branch` (it is a
   local branch — `git rev-parse` it to confirm; if missing, the campaign hadn't started — recreate via §0).
2. Slices at `merged` are already **in integration** — skip them; do NOT re-merge.
3. For each non-`merged` slice, its live teammate is gone. Re-spawn its implementer with a **context
   packet** rebuilt ENTIRELY from the ledger record (the dead teammate held nothing recoverable):
   - the slice's ACs and `base_sha`/`branch`/`worktree_path`;
   - the prior committed diff — `git -C <worktree_path> diff <base_sha>...HEAD` plus the recorded
     `files_changed` as the summary;
   - the **last reviewer findings** — the record's `last_defects` (this is the ONLY place they survive;
     the `rev-<id>` that produced them was torn down in §2). `[]` means the last verdict was PASS, so
     tell the implementer to re-verify rather than fix.
   Resume the review loop from there (a fresh `rev-<id>` re-reviews after the implementer's next idle).
4. **Interrupted campaign ship:** if every slice is `merged` but top-level `campaign_merge_sha` is null,
   §5b was cut off mid-flight — resume it (check whether `campaign_pr` already opened before re-pushing
   the integration branch).
5. Never SendMessage an `agent_id` from a prior session — it no longer exists. Drop the stale `agent_id`
   and record the new one when the re-spawned implementer comes up.

## Ledger field rules (per `ledger-entry.schema.json`)

| transition | set |
| --- | --- |
| campaign start (§0) | top-level `integration_branch` |
| dispatch | `phase=dispatched`, `agent_id`, `worktree_path`, `branch`, `base_sha`, `round_count=0` |
| impl idle | `report_file`, `files_changed` (from the report — feeds the resume packet) |
| verdict read | `verdict_file` (then tear down `rev-<id>`) |
| CHANGES | `phase=changes`, `round_count++`, `reviewer_verdict=CHANGES`, `last_defects=<defects>` |
| PASS+gate | `phase=pass`, `head_sha`, `reviewer_verdict=PASS`, `last_defects=[]`, `gate_result=pass`, `boundary_ok`, `ac_evidence` |
| boundary breach | `phase=blocked`, `boundary_ok=false`, `escalation` |
| ESCALATE | `phase=held`, `escalation` |
| integrate (§5a) | `phase=merged`, `merge_sha=<integration-merge commit>`, `ship_pr=null` |
| campaign ship (§5b) | top-level `campaign_pr`, then `campaign_merge_sha` on confirm |

(`shipped` is unused per-slice — the only ship is the campaign-level integration→main in §5b.)
Always stamp `updated_at` (an ISO-8601 string you generate in the main loop — not inside any
workflow/Bash that would re-run on resume).

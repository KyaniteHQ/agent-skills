# slice-conductor — teammate dispatch prompts

The exact prompts the lead uses to spawn `impl-<id>` and `rev-<id>`, and to re-enter a live
implementer. They bake in the platform quirks from `memory/agent-teams-lifecycle-findings.md`: a
teammate's `skills:` frontmatter is NOT applied (so name `/tdd` explicitly), bare replies are
unreliable (so demand both a SendMessage AND a written report file), and the worktree is created BY
THE LEAD (so the teammate is told its path, never asked to make one).

Fill the `<…>` placeholders from `slices.json` + the ledger before spawning. The implementer is spawned
with `subagent_type: "implementer"`, `name: "impl-<id>"`, `run_in_background: true` (the Agent
tool's field is `subagent_type`, NOT `agentType` — that's the Workflow harness). The reviewer with
`subagent_type: "reviewer"`, `name: "rev-<id>"`, `run_in_background: true`. NEVER use
`subagent_type: "general-purpose"` — it has the Agent tool and can self-spawn into a runaway. Do NOT
pass `isolation: "worktree"` (it's a no-op and misleads).

**`<report_file>` and `<verdict_file>` MUST be ABSOLUTE paths** — e.g.
`$(git rev-parse --show-toplevel)/orchestration/runs/<slug>/reports/<id>.json`. The teammate's
cwd is its own worktree, so a RELATIVE path would write the report INTO the worktree
(`<worktree>/orchestration/runs/...`, which is gitignored and deleted at integrate) where the
lead — reading from the MAIN checkout — never finds it, silently demoting the "reliable file channel"
to the unreliable SendMessage reply. The lead `mkdir -p`s the main-tree `runs/<slug>/reports/` dir and
fills these placeholders absolute.

## Implementer spawn prompt (`impl-<id>`)

```
You are implementing slice <id> (<title>) as a teammate of the team lead.

WORKTREE: cd into `<worktree_path>` and do ALL work there — it is your isolated git worktree on branch
`slice/<id>`, already created for you off the campaign integration branch's tip. Never touch the main
checkout; never `cd` out.

SCOPE — touch ONLY these paths (your declared touch_set): <touch_set list>. Editing anything outside
this set fails the lead's boundary check and blocks the slice. If you believe you must touch another
file, STOP and report it instead of doing it.

ACCEPTANCE CRITERIA (code slice: write the failing test from each FIRST; non-code slice: verify each
against its evidence):
<AC1 text>
<AC2 text>
...

METHOD — pick by slice type (infer from the touch_set + ACs):
- CODE slice -> strict TDD: invoke the `/tdd` skill explicitly (your frontmatter skills are not
  auto-loaded as a teammate); red -> green -> refactor, one AC at a time.
- NON-CODE slice (docs/schema/config/SQL/Linear/research) -> TDD does NOT apply; do not invent a test.
  Make the smallest change per AC, then verify it against the AC with the matching evidence (the doc has
  its content + resolving links; the schema/JSON/YAML validates; SQL parses; the artifact exists).
Either way keep the project's static-analysis checks clean, and run the project's offline gate command
(from project-config `gate_command`, or the project's AGENTS.md/CLAUDE.md) as the regression guard.
Never run live/network runs — that is the lead's attended job.

INVARIANTS: only project-config secret identifiers (e.g. a hashed or opaque id) leave worker memory
(no raw project secrets/PII in logs/metrics/commits); no ssl=False / cert-ignore; add deps only via
the project's standard dep-management tool if the slice names one (never hand-edit lock files
directly).

COMMIT on your branch when the acceptance test is green — do NOT push, do NOT merge to main, do NOT
touch Linear (the lead owns those; your Linear writes would silently no-op).

REPORT — two channels, both required:
1. Write your report JSON (the implementer-report contract) to `<report_file>` (an ABSOLUTE path —
   write there exactly, even though your cwd is the worktree).
2. Reply to the lead by calling SendMessage with to:"team-lead" and the same JSON. Your plain text is
   NOT visible to the lead — you MUST SendMessage or the lead never sees you finished.
Report JSON: {"issue":"<id>","branch":"slice/<id>","commit":"<sha>","files_changed":[...],
"acs_ticked":[...],"acs_unmet":[...],"at_command":"...","at_result":"...","full_suite":"NNN passed /
M skipped","static_analysis":"clean|...","linear_state_set":"In Progress|Blocked|ESCALATE",
"escalation":null,"report_file":"<report_file>"}

AC-TEXT DRIFT: if an AC's wording contradicts the shipped design (names a non-existent state/field, or
demands behavior the code deliberately lacks), do NOT change code to match or silently edit the AC —
report `linear_state_set:"ESCALATE"` with the exact mismatch. The lead asks the owner.
```

## Reviewer spawn prompt (`rev-<id>`)

```
You are the adversarial reviewer for slice <id>, a teammate of the team lead. You are SEPARATE from the
implementer — be skeptical. Read-only: never Edit/Write/commit, never touch Linear.

INPUT: branch `slice/<id>` at commit `<sha>` in worktree `<worktree_path>`. The acceptance criteria:
<AC1 text> / <AC2 text> / ...

SCOPE: this slice branched off the campaign integration tip `<base_sha>`, NOT `main`. Review ONLY this
slice's own diff — `git -C <worktree_path> --no-pager diff <base_sha>...HEAD` — and judge ONLY this
slice's ACs. Do NOT re-flag code already present at `<base_sha>` (earlier slices already passed review;
their files are outside this slice's touch_set, so a defect there is unfixable here). The offline suite
must be green (0 failed); "no drop in passed count" is measured against `<base_sha>`, not `main`.

REVIEW: for each in-scope AC — CODE slice: confirm (a) the code implements it on a REAL path (not a
stub/unwired component — trace the call site) and (b) a NON-VACUOUS test asserts it (would fail if the
behavior were removed). NON-CODE slice (docs/schema/config/SQL/Linear/research): no test to demand — do
NOT fail it for "no test"; confirm the deliverable satisfies the AC and re-run its verification (doc
content + links; schema/JSON validates; SQL parses; artifact exists). Run the project's offline gate
command (from project-config `gate_command`, or the project's AGENTS.md/CLAUDE.md) — it MUST stay
green (no drop in passed count). Sweep the invariants (project secrets/PII never in
logs/metrics/commits, no ssl=False, no raw-secret siblings, dep changes only via the project's
standard dep-management tool).

REPORT — two channels, both required (write to `<verdict_file>` — an ABSOLUTE path, write there exactly
even though your cwd is the worktree — AND SendMessage to:"team-lead"):
{"issue":"<id>","commit":"<sha>","verdict":"PASS|CHANGES|ESCALATE","suite":"NNN passed / M skipped /
K failed","ac_check":[{"ac":"AC1","status":"met|unmet|vacuous-test|unwired|drift","note":"..."}],
"defects":["file:line — why it fails the AC/invariant; [] if none"],"escalation":null,
"merge_recommendation":"merge|re-run implementer with defects|hold for owner"}

PASS only when every in-scope AC is backed by real evidence (code+test for a code slice; the verified
deliverable for a non-code slice) AND the suite is green AND no invariant is violated. CHANGES for
concrete fixable defects. ESCALATE for an AC-wording decision only the owner can make.
```

## Re-dispatch on CHANGES (SendMessage to the LIVE `impl-<id>`)

Do not spawn a fresh implementer — message the live one so it keeps its context:

```
SendMessage to:"impl-<id>":
Reviewer returned CHANGES on your slice. Fix each defect (red -> green, TDD), stay within your
touch_set, re-commit on `slice/<id>`, update your report file at `<report_file>`, then reply to me via
SendMessage to:"team-lead" with the updated report JSON when the suite is green again.
Defects:
<defect 1>
<defect 2>
```

## Resume re-spawn (after `/resume` — the prior teammate is gone)

Spawn a fresh `impl-<id>` but hand it the context packet so it doesn't re-onboard from scratch:

```
You are RESUMING slice <id>. A prior teammate did the work below; continue from it — do not restart.
Your worktree `<worktree_path>` (branch `slice/<id>`) already has these commits.
[then the standard implementer prompt above, plus:]

PRIOR PROGRESS:
- commits so far: <head_sha> — <files_changed>
- ACs already green: <acs_ticked>
- last reviewer findings to address: <defects or "none — was at PASS, re-verify">
```

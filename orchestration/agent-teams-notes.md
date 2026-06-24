# Agent-teams platform notes (for slice-conductor)

Repo-vendored copy of the spike- and doc-verified Claude Code agent-teams behavior the
`slice-conductor` skill is built around. (The richer narrative lives in the Claude project memory
`agent-teams-lifecycle-findings`, but skills must cite a repo-relative path, so this is the canonical
reference for executors.) Verified 2026-06-17 against a live spike + `code.claude.com/docs/en/agent-teams`
(v2.1.178+).

## Hard safety rules (read first)

- **NEVER spawn `general-purpose` teammates.** A `general-purpose` agent has the **Agent tool**, so it
  can self-spawn — a real fan-out runaway hit **120+ nested agents and burned ~$242**, unkillable from
  the main loop (only a user `Ctrl+C` reaped it). Spawn ONLY `implementer` and `reviewer`,
  whose `tools` allowlists have **no Agent tool** (they structurally cannot self-spawn). This is the
  single most important rule in the conductor.
- **Worktrees are created BY THE LEAD.** The Agent tool's `isolation:"worktree"` flag is a **no-op** for
  main-loop teammates — a spike teammate spawned with it ran in the **main tree** and wrote files there
  (cwd-bleed). Always `git worktree add` by hand and tell the teammate its path. Run the boundary check
  (`git diff <base_sha>...HEAD` ⊆ touch_set) after every teammate turn.

## Spawn shape (the Agent tool, NOT the Workflow harness)

- Spawn a teammate via the **Agent tool** with `subagent_type` (NOT `agentType` — that's the Workflow
  harness field), plus `name`, `run_in_background: true`. Do NOT pass `isolation` (no-op + misleading).
  Example intent: `subagent_type: "implementer"`, `name: "impl-<id>"`, `run_in_background: true`.
- Address a live teammate via **SendMessage** by `name` (or the returned `agentId`).
- A teammate's `skills:`/`mcpServers:` frontmatter is **NOT applied** when it runs as a teammate — so
  name `/tdd` explicitly in the spawn prompt; its `tools` allowlist + `model` ARE honored. Coordination
  tools (SendMessage, Task*) are always available.
- Teammate permission = the **lead's** mode at spawn (not the subagent's `permissionMode`) — run the
  lead in a mode that lets teammates Edit/Write/commit.

## Communication

- Bare questions to a teammate yield only `idle_notification` pings — to get a result back, the prompt
  MUST say **"reply via SendMessage to team-lead"**. Even then, treat the SendMessage reply as a
  convenience and the teammate's **report FILE** as the reliable channel.
- Persistent named teammates DO retain context across SendMessage re-entry (a spike recalled a token
  through two re-entries) — this is what lets the same implementer fix across review rounds.

## Limits that shape the design

- **No nested teams.** The lead spawns BOTH `impl-<id>` and `rev-<id>`; a teammate cannot spawn another.
  The lead routes every CHANGES packet and owns the ledger (do NOT rely on rev->impl direct messaging).
- **`/resume` kills in-process teammates.** They don't survive resume → the run **ledger** is the
  durable truth; on resume, re-spawn implementers for non-`merged` slices with a context packet.
- **Task status can lag** — trust the ledger + reviewer verdict + boundary check, never the task board.
- **Team size guidance: 3-5 teammates.** Note each slice is ≤2 teammates (impl + a short-lived
  reviewer), so the slice concurrency ceiling (≤5) plus reviewers can exceed the teammate guidance —
  keep the effective in-flight slice count modest.
- **Prereq:** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (set in `~/.claude/settings.json`); confirm a
  live `~/.claude/teams/session-<id8>/` dir and fail closed if absent.

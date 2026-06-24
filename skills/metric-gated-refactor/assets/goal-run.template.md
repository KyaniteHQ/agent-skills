# Overnight goal: metric-gated refactor campaign

<!-- TEMPLATE. /metric-gated-refactor Phase A fills the {{placeholders}} and writes
the rendered copy to .claude/prompts/refactor-goal-run.md. Launch the rendered copy
with:  /goal .claude/prompts/refactor-goal-run.md  — do not run this template. -->

Run the `metric-gated-refactor` skill's autonomous loop (Phase B) fully
autonomously. Read the skill first — `.claude/skills/metric-gated-refactor/SKILL.md`
(the admission rule + anti-gaming invariants are binding) — then
`references/loop-spec.md` (the algorithm) and `references/metrics.md` (the exact
commands). Ground per AGENTS.md / CLAUDE.md / `.claude/rules/*.md` before touching
anything.

## The contract (binding)

- A refactor needs BOTH a metric trigger AND a named semantic problem from the
  closed list (+ a boundary claim for Louvain; composition root exempt). No invented
  debt. Metric improvement alone is never sufficient.
- Anti-gaming: max CC drops by the agreed bounded delta; no new rank-C+ helper;
  total touched-file CC not increased; tests prove behaviour, not shape. Otherwise
  revert the step.
- Full offline gate before every merge to `integration`. The conditional, SERIAL
  optional smoke/canary command does NOT replace the offline merge gate;
  if it FAILS, stop and report before any PR/merge.
- All issue-tracker writes from YOUR main loop (subagents report-only). Never write
  MEMORY.md / the memory dir. PII + secrets rules absolute. Never edit pyproject.toml / uv.lock.
- Issue lifecycle: In Progress on start → tick ACs only with observed, redacted
  evidence → Done with branch + SHA. Findings as issue comments.

## Campaign config (locked in Phase A)

- **Scope (packages/modules in play):** {{SCOPE}}
- **Thresholds (radon rank, Louvain rule):** {{THRESHOLDS}}
- **Stop after K consecutive dry rounds:** {{K_DRY_ROUNDS}}
- **Per-run step budget:** {{STEP_BUDGET}}
- **Slices that require a smoke/canary run (optional):** {{CANARY_SURFACES}}

## Stop / done condition

Loop until K consecutive dry rounds (no admissible candidate). Then run one
end-of-campaign attended smoke/canary (if configured), PREPARE one squash PR `integration → main`,
and STOP — merging is the owner's separate go-ahead. Post a run summary on the parent
campaign issue: per-candidate metric before→after, the named problem, the SHA, and
anything the morning review needs.

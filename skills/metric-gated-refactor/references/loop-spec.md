# Autonomous loop spec (Phase B)

Runs only on an explicit go-ahead. Encoded by `.claude/prompts/refactor-goal-run.md`
and executed in a fresh `/goal` session. Metric commands: `references/metrics.md`.
Admission rule + anti-gaming invariants: `SKILL.md` (binding).

```
SETUP (once): integration branch off main · parent Linear campaign issue ·
  /tmp/refactor/<date>.md worklog.

LOOP (round):
  1 MEASURE prod-only (radon + Louvain) on the integration tip.
  2 ADMIT — keep a candidate only if it has a metric trigger AND a named semantic
    problem (+ a boundary claim for Louvain; composition root exempt). STOP-GATE:
    no admissible candidate → dry_round++; dry_round ≥ K (default 2) → STOP
    ("architecture good by measurement"). Else dry_round = 0.
  3 PARTITION — candidates touching shared/core files (as listed in scope config)
    run SEQUENTIAL; disjoint-file candidates fan out into ≤N worktrees.
  4 per candidate:
    a orchestrator: file a Linear sub-issue under the campaign parent (DoD = bounded
      metric delta + named problem; AC = suite green + metric improved + no worse
      coupling + behaviour preserved). `git worktree add` an isolated branch.
    b implementer subagent (in the worktree): research the best refactor — reuse
      existing patterns, no asking — and apply it via /tdd refactor discipline (the
      existing suite IS the regression net; add characterization/exhaustiveness tests
      only where the refactor exposes an untested seam, new tests pass 5×). The
      anti-gaming invariants hold. Report evidence only; NO issue-tracker writes.
    c orchestrator (VERIFY pwd / git status / branch first — cwd-bleed trap): run the
      full offline gate. Red → revert the candidate, log, skip.
    d RE-MEASURE: target max CC dropped by the agreed delta AND no new rank-C+ helper
      AND total touched-file CC not increased AND coupling no worse? No → REVERT.
    e REVIEW: run /code-review READ-ONLY on the diff. Apply ONLY specific, concrete
      findings, then re-gate. Do NOT auto-run /simplify (churn risk).
    f SMOKE/CANARY — only if the slice touches modules listed in {{CANARY_SURFACES}}.
      SERIAL barrier: run the project-defined canary command (supplied in campaign
      config). Pure non-runtime refactors skip it.
      The canary does NOT replace the offline merge gate; if it FAILS, stop and
      report — do not merge the candidate or open the PR.
    g MERGE the worktree branch → integration as ONE commit (message = named problem
      + metric before→after). `git worktree remove`.
    h orchestrator: tick the sub-issue ACs (redacted evidence + SHA) → Done. Append
      3 lines to /tmp/refactor/<date>.md — CHANGED / BROKE / TESTED.
  5 (no MEMORY.md writes — owner-controlled surface.)

END LOOP:
  - one end-of-campaign attended smoke/canary (if configured);
  - PREPARE one squash PR integration→main (`gh pr create`) and STOP. Merging is a
    SEPARATE go-ahead — do not babysit/merge unless the owner approves. Post a run summary
    on the parent campaign issue.
```

## Optional smoke/canary command

Supply the project-specific canary command in the campaign config ({{CANARY_COMMAND}}).
If none is configured, step f is skipped for all slices.

## Offline gate (every slice — the per-step regression net)

```
uv run ruff check . && uv run mypy --strict . && \
  timeout 300 uv run pytest -q -p no:cacheprovider
```

Prepend any project-required env vars (e.g. `env TEST_ENV=value`) before `uv run pytest`
as specified in the project's AGENTS.md or CLAUDE.md.

# Bounce-campaign trajectories (stop-rule calibration fixture)

The v2 loop's stop rules (`.claude/workflows/plan-bounce-loop.js` -> `decide()`) are calibrated against
real bounce campaigns mined from Claude Code session transcripts (audited 2026-06-18). Each row is
one plan's score path across hand-run rounds. **Only 1 of 12 reached the 95 target by hand** -- the gap
the loop closes.

| Plan slug | Trajectory | Outcome | What the loop should do |
|---|---|---|---|
| lively-dazzling-blossom | 72 -> 89 -> 89 -> 95 | reached 95 | continue past the 89->89 plateau (an open HIGH finding remained) -> EXECUTE at 95 |
| add-resilience-observability | 44 -> 57 -> 54 -> 58 -> 72 -> 76 -> 72 | never converged | NEEDS-HUMAN (oscillation; maxRounds) |
| i-want-to-do-rosy-scroll | 46 -> 72 -> 42 -> 74 | never converged | NEEDS-HUMAN at round 3 (net regression 72->42) |
| make-the-plan-first-steady-storm | (fail) -> 41 -> 76 -> 76 -> 74 | never converged | NEEDS-HUMAN (regression at round 5; model-rotation fired on round 1) |
| team-42-add-retry-logic | 72 | single round | (predicted the 3 Greptile P1s) |
| majestic-puzzling-mist | 58 | single round | continue |
| orchestration-skill | 54 | single round | continue |
| to-slices/SKILL.md | 46 -> 58 | two rounds | continue |
| slice-conductor/SKILL.md | 41 -> 68 | two rounds | continue |
| can-you-check-the-glimmering-flurry | 55 | single round | continue |
| skill self-test (i-want-to-create-cosmic-nest) | 76 | caught its own stale-artifact bug | continue |
| check-the-coolify-project-agile-horizon | (user-killed ~90s) | bypassed | n/a |

## Calibration notes

- **`72 -> 89 -> 89` must NOT trip SHIP-AS-IS at the plateau** -- the 89 rounds still had an open HIGH
  finding; fixing it reached 95. Hence SHIP-AS-IS requires `0 open high/critical findings`, not just
  `0 structural blockers`.
- **`46 -> 72 -> 42`** is the canonical NEEDS-HUMAN: a revision that backfired. The net-regression check
  (`score[n-1] - score[n-3] < 0`) catches it at round 3, before a wasted round 4.
- **Model rotation** (the `make-the-plan-first-steady-storm` round-1 failure) fired on a
  `404 unknown model: "gpt-5.5"` and recovered on the next fallback -- the session-8 dead-end the
  fallback chain fixes.

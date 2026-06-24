# PR description template (babysit-pr §2)

Fill this in and pass it to `gh pr create --body-file`. The goal is a reviewer (human **and** Greptile,
which reads the description) orienting in seconds: what changed, where to look, what could break. A thin
one-line body is what makes `/check-pr` raise description-gap findings later — spend the two minutes here.

Adapt the sections to the slice; drop a section that genuinely doesn't apply rather than padding it. Never
include secret values, tokens, or sensitive identifiers in the body.

```markdown
## TL;DR
<1–3 sentences that match the actual diff — what this slice does and why. If the TL;DR and the diff
disagree, the diff wins; fix the TL;DR.>

## What landed
- <change> (ISSUE-NNN)
- <change> (ISSUE-NNN)

## Files to review
**Core (read these):**
- `path/to/file.py` — <what changed and what to scrutinize>

**Mechanical / generated (skim):**
- `path/...` — <formatting, lockfile, fixture regen, rename — no logic>

## Risk / migration / rollout
- Behavior change: <none | what user-visible behavior moves>
- Ordering: <FSM table / schema / config / SQL changes that must land in a given order, if any>
- Rollout: a `v*` tag (not this merge) triggers `release.yml` → deploy; this PR merging does not deploy.

## Test coverage
- Offline gate: <which tests exercise the change — lint + type-check + test suite all green locally>
- Gaps: <any live-validation step the offline gate can't cover, e.g. a real integration call>

## Links
- Issue tracker: <ISSUE-NNN URL>
- Plan-bounce artifact (if planned): `.claude/plan-bounce/<slug>/iteration-*/codex-review.json`
- Dashboards / runbook: <relevant runbook section or dashboard — only if it explains intent>
```

## Notes

- **Core vs mechanical is the highest-leverage section.** A reviewer who knows which 2 files carry the
  logic (and which 8 are generated churn) reviews 5× faster. If you can't name the core files, the slice
  may be doing too much — see the §2 size check.
- **Don't hide behavior changes inside "mechanical".** Anything that changes what the system does belongs
  in Core + Risk, never buried in the skim list.
- For a verbose mechanical block (retry/backoff, error mapping), a one-line plain-English summary of the
  algorithm in "Files to review" saves the reviewer from re-deriving it from the diff.

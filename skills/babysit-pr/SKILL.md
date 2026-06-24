---
name: babysit-pr
description: Drive a slice's squash-merge pull request to `main` through the full review→fix→merge pipeline. Use when shipping a slice to `main` (the trunk + releasable branch), or when the user says "babysit the PR", "ship this slice", "merge this PR", or asks to shepherd a PR until it is green and merged. Runs the pre-PR local quality loop (incl. a deslop pass + a local `greptile review`), opens the PR with a reviewer-ready description, polls CI gate checks, delegates the Greptile review loop to `/greploop`, fixes findings, and squash-merges only when every check is green and the reviewer is satisfied — then deletes the slice branch. Trigger with "babysit the PR", "ship this slice", "merge this PR to main", or "get this PR green and merged". Broader than `/greploop` (Greptile loop only) and `/check-pr` (one-shot triage) — babysit-pr owns opening, the gate polling, and the squash-merge.
version: "1.2"
compatibility: Requires git and gh (GitHub CLI) authenticated; invokes the /code-review, /simplify, /greploop slash commands and the greptile CLI.
allowed-tools: Bash(gh:*) Bash(git:*) Bash(greptile:*) Skill
---

# babysit-pr

Shepherd a pull request (a working branch — short-lived slice branch or a longer-lived branch like `integration` — → `main`) from open to squash-merged without leaving findings or red checks behind. `main` is the single trunk **and** the releasable branch, kept **clean and linear: one PR = one squashed commit** (see CLAUDE.md "Git flow"). Every PR lands via squash-merge, the branch is deleted on merge, and a `v*` tag — not a merge — is what triggers a deploy.

## When to use
- Shipping a **real slice** to `main` after the work is done and the offline gate is green locally.
- Any PR the user explicitly asks you to babysit to green-and-merged.

**Heavyweight path — confirm before launching.** This spawns multiple review agents and a multi-round
Greptile loop, which is overkill for small changes. It is the ship step offered *after* implementation +
a green local gate, so when implementation finishes don't auto-launch it: offer the ship step and ask
the user which path (see CLAUDE.md "Build/maintenance protocol"). **Small / maintenance changes** (docs,
one-line fixes, config tweaks) go **straight to `main`** (commit + push, no PR) per CLAUDE.md git-flow --
do NOT run this pipeline for those.

## Assumptions
- The current repo: `$(gh repo view --json nameWithOwner -q .nameWithOwner)`; `gh` is authenticated.
- The offline gate command: detect from the project's `./AGENTS.md` or `./CLAUDE.md`; fall back to reading `package.json` / `pyproject.toml` / `Makefile` to identify the lint + type-check + test invocation.
- CI check names: discovered dynamically via `gh pr checks <num> --json name,bucket,state` — treat "all required checks green" as the merge gate regardless of count or name. If branch protection is not server-enforced, this skill's green-gate is the enforcement.
- All Linear writes happen from the main loop, never a subagent.

## Pipeline

### 1. Pre-PR local loop (do NOT open the PR until this is clean)
1. Confirm the slice branch is up to date with `main`. Capture the pre-rebase tree first so a merge/rebase can't silently change content: `ORIGINAL_TREE=$(git rev-parse HEAD^{tree})`, then `git fetch origin && git merge origin/main` (or rebase) and resolve any conflict. When you did NOT intend a content change, `git diff origin/main...HEAD --stat` should list only your slice's files — an unexpected delta means the history op went sideways; stop and re-resolve rather than pushing it.
2. **Carry forward any plan-bounce blockers.** If this work was planned with `/adversarial-plan-bounce`, re-read its artifact (`.claude/plan-bounce/<slug>/iteration-*/codex-review.json`) and confirm every `structural_blocker` and `held_decision` is addressed in the diff. These design-time adversarial findings reliably predict what Greptile flags post-open (a planning blocker about, say, an uncovered cancellation path tends to resurface as the reviewer's P1s) — clearing them now saves `/greploop` iterations later.
3. Run `/code-review` on the diff vs `main` (`git diff main...HEAD`). Fix every correctness finding; re-run until clean.
4. Run `/simplify` for reuse/altitude cleanups; apply.
5. **Deslop the agent-authored diff.** Agent-authored code carries predictable tells that read as noise to a reviewer and reliably trip Greptile. Scan `git diff main...HEAD` for slop mapped to the project's rules (check `.claude/rules/` and `.greptile/`) and strip it behavior-unchanged: redundant comments that merely restate the code; defensive error handling wrapped around trusted internal paths; broad escape hatches (`Any` / `cast(...)` / `# type: ignore`) used to dodge strict type-checking instead of modelling the type; deep nesting an early return would flatten. This complements `/simplify` (altitude/reuse) and the `code-cleanup:slop-remover` agent — it does not replace them. Keep edits minimal; step 7's offline gate re-proves behavior.
6. **Local Greptile pass (before the PR exists):** commit the work, then run `greptile review -b main --agent`
   from the repo root (the CLI reviews committed commits vs `main`; it ignores uncommitted changes; the
   `/greptile-cli` skill documents every command + flag). Triage the findings — fix high-confidence
   correctness/invariant hits, note false positives. Advisory only: the
   offline gate + CI are the hard gate. Greptile applies the repo rules in `.greptile/` if present. Needs `greptile
   login` once per machine; if the CLI isn't available, skip this
   and rely on the post-open `/greploop` pass.
7. Run the full offline gate locally. It MUST be green. If red, fix and repeat from step 3.

**Committing in a shared tree** (a concurrent `/goal` or other session has unrelated files dirty): commit ONLY your files — scoped `git add <your-paths>`; the pre-commit/pre-push hooks stash unstaged files so the gate runs on your snapshot alone. Two gotchas: (a) the commit-stage `detect-secrets` hook may rewrite `.secrets.baseline` in place (line-number shifts from your edits) and abort the commit — confirm the baseline diff is only `line_number`/`generated_at`, then `git add .secrets.baseline` and re-commit; (b) a `git push` can race the concurrent writer during the hook's stash/restore (fails "files were modified by this hook" even though the suite passed) — retry once, and if it persists push from an isolated clone. Never `git stash` or switch branches in the shared tree — it disrupts the other session. (Complements the CLAUDE.md dirty-tree guidance.)

### 2. Open the PR
- **Size check first.** A slice should be reviewable from its diff plus notes. If `git diff main...HEAD --stat` is so large that no description could make it reviewable, that is a decomposition problem, not a writing problem — recommend splitting it via `/to-slices` instead of polishing a wall of diff. (Slices are meant to be small; a giant one usually means the DAG was cut too coarse.)
- **Write a reviewer-ready description, not a one-liner.** A good body is what lets Greptile and a human reviewer orient fast, and it directly shrinks the description-gap findings `/check-pr` raises later. Fill the template in `references/pr-body.md` — TL;DR that matches the actual diff, what-landed with issue refs, a core-vs-mechanical file split (so the reviewer reads the files that matter, not generated churn), risk/migration/rollout, test coverage, and links. Never include secret values, tokens, or sensitive identifiers in the PR body.
- `gh pr create --base main --head <slice-branch> --title "<slice title>" --body-file <path>` — write the filled template to a temp file and pass `--body-file` (a multi-section body does not survive inline `--body` shell-escaping). Use `$(gh repo view --json nameWithOwner -q .nameWithOwner)` if the repo needs to be specified explicitly.
- Capture the PR URL and number.

### 3 + 4. Review + fix loop (poll until green AND reviewed)
Poll the checks to green. Prefer `gh pr checks <num> --watch --fail-fast` to block until a check fails or all pass — tighter than a blind `/loop` interval; reach for `/loop` (every 2–3 min) only when you need to interleave the Greptile and `/check-pr` passes between polls. Each iteration:
- `gh pr checks <num> --json name,bucket,state,workflow,link` is the source of truth — it covers every PR-attached check (not just GitHub Actions, which `gh run list` is limited to), and the `link` field locates the log for an external/non-GHA check.
- **Fix one failure at a time.** Read the first failed job's log (`gh run view <run-id> --log-failed`, or follow its `link`), fix that single root cause on the slice branch, commit, push; the push re-triggers checks. Then re-read the *full* check set — it can change between pushes — and repeat. Resist batching speculative fixes: one cause per push keeps the signal legible.
- Drive **Greptile** to clean with the `/greploop` skill (the installed external reviewer, app slug
  `greptile-apps`): it posts `@greptileai review`, parses the confidence score + unresolved inline comments
  (incl. the edited general "Prompt to fix all with AI" comment), fixes actionable items, replies
  (`Fixed in {sha}` for real fixes — thread left open for the reviewer to verify; `Won't fix: {reason}` +
  resolve for false positives), resolves threads, and loops to 5/5 / zero-unresolved (max 5 iterations).
  Greptile reviews are `COMMENTED` (advisory), not a required check; the required CI checks are the merge gate.
  Greptile enforces the repo rules in `.greptile/` if present. For a single triage pass instead of the loop use
  `/check-pr`. Degraded mode (`/code-review` as the reviewer) is the fallback only if the app is ever
  uninstalled. Never echo secret values, tokens, or sensitive identifiers into a reply.
- Sweep **human reviewer comments + PR-description completeness** with `/check-pr` (breadth — `/greploop`
  covers only Greptile, not humans or the description): address actionable human comments, fill description
  gaps, resolve those threads. Skip if the PR has no human reviewers.
- Stop looping when: ALL required checks are green AND `/greploop` reports 5/5 with zero unresolved AND `/check-pr` finds no open actionable human comments (or degraded: `/code-review` returns no findings on the final diff).

### 5. Squash-merge + delete branch
- Confirm green one last time: `gh pr checks <num> --json name,bucket,state` — every `bucket` is `pass`.
- `gh pr merge <num> --squash --delete-branch` (collapses the slice's commits into one on `main` and removes the branch). The squash preserves the branch tree — GitHub computes the merge — so the merged content equals the PR's "Files changed"; nothing extra slips in. Do NOT use `--admin` to bypass red checks.
- Tag a release from `main` only if the user asks (`v*` triggers `release.yml` → deploy).
- Report the merged PR URL and the squash commit SHA.

## Examples

**Example 1 — ship a finished slice**
Input: `babysit the PR for this slice`
Output: runs the pre-PR loop (`/code-review`, `/simplify`, local `greptile review`, offline gate), opens the
PR with the Linear ref, drives checks + `/greploop` to green/5-of-5, squash-merges, deletes the branch, and
reports the merged URL + squash SHA.

**Example 2 — an already-open PR**
Input: `get PR 42 green and merged`
Output: skips straight to the §3+4 poll loop on PR 42 — fixes red checks, delegates the Greptile loop to
`/greploop`, and squash-merges once all required gates are green.

## Guardrails
- Never merge with a red required check or an unresolved actionable review finding.
- Never `--no-verify`, never bypass branch protection.
- Never put a secret value, token, or sensitive identifier in the PR body or a comment.
- If a check is red for an infra/flake reason (not the diff), re-run it (`gh run rerun`) once; if it stays red, surface it rather than merging around it.
- If a check is red for a cause **unrelated to your diff that is already green on `main`**, `git merge origin/main` to pick up the existing fix rather than adding an unrelated change to this PR — keep the slice's diff strictly its own.

## Notes
- **Greptile** is the installed external reviewer (app slug `greptile-apps`). The app-aware path
  is `/greploop` (loop to 5/5) or `/check-pr` (one-shot triage); `/code-review` is the degraded fallback.
  Pre-PR, `greptile review` (CLI) catches issues locally before the PR exists. Greptile enforces the
  repo-level rules in `.greptile/` (config.json + rules.md) if present. See CLAUDE.md "Greptile review surfaces"
  for setup and the review surfaces.
- Polling cadence and the reviewer path are the two things to adjust per run.

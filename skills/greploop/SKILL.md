---
name: greploop
description: Iteratively drive a GitHub pull request to a clean Greptile review — 5/5 confidence with zero unresolved comments. Triggers a fresh Greptile review, parses the confidence score and unresolved inline comments, fixes every actionable finding, replies, resolves the threads, pushes, and re-reviews (max 5 iterations). Use when the user wants to fully resolve Greptile's findings on a PR or "get the PR to 5/5". This is the Greptile review loop that babysit-pr delegates to; it does NOT open the PR, poll CI gate checks, or squash-merge — that is babysit-pr's job. Trigger with "/greploop", "/greploop 42", "drive this PR to 5/5", "resolve all of Greptile's comments", or "loop Greptile until it's happy".
license: MIT
version: "1.3"
author: greptileai (adapted)
compatibility: Requires git and gh (GitHub CLI) authenticated, and Greptile (greptile-apps[bot]) installed on the repo.
allowed-tools: Bash(gh:*) Bash(git:*)
---

# Greploop

## Overview

Iteratively fix a PR until Greptile gives a perfect review: **5/5 confidence, zero unresolved comments**.
Each pass triggers a fresh Greptile review, parses the confidence score + unresolved comments, fixes the
actionable ones, replies, resolves the threads, pushes, and re-reviews — up to 5 iterations. Greptile is
advisory here (`COMMENTED`, not a required check); a clean greploop is a quality signal, while the repo's
own CI gate checks are the actual merge gate that `babysit-pr` enforces. Use `/check-pr` for a single
triage pass instead of a loop.

Adapted from [greptileai/skills](https://github.com/greptileai/skills) (MIT) — trimmed to the GitHub path,
the `@greptileai` trigger, the `greptile-apps[bot]` reviewer, and a generic reply policy.

## Contents

- [Prerequisites](#prerequisites)
- [Inputs](#inputs)
- [Instructions](#instructions) — 1. Identify the PR · 2. Loop (A trigger · B fetch · C exit · D fix · E reply+resolve · F push) · 3. Report
- [Examples](#examples)
- [Error Handling](#error-handling)
- [Output format](#output-format)

## Prerequisites

- `git` and `gh` (GitHub CLI) installed and authenticated (`gh auth status`).
- Greptile (`greptile-apps[bot]`) installed on the repo so `@greptileai review` triggers a review.
- An open PR for the branch (or pass a PR number explicitly).

## Inputs

- **PR number** (optional): if not provided, detect the PR for the current branch.

## Instructions

### 1. Identify the PR

```bash
gh pr view --json number,headRefName -q '{number: .number, branch: .headRefName}'
```

Switch to the PR branch if not already on it.

### 2. Loop (max 5 iterations — avoids runaway cycles)

#### A. Trigger a Greptile review

Push the latest changes (if any), then give checks a moment to register:

```bash
git push
sleep 5
```

Check whether Greptile is already running before posting a fresh trigger comment:

```bash
GREPTILE_STATE=$(gh pr checks <PR_NUMBER> --json name,state | jq -r '.[] | select(.name | test("greptile"; "i")) | .state')
if [ "$GREPTILE_STATE" != "PENDING" ] && [ "$GREPTILE_STATE" != "IN_PROGRESS" ]; then
  gh pr comment <PR_NUMBER> --body "@greptileai review"
fi
```

Then poll for completion. **Greptile posts a `COMMENTED` review + an edited general comment;
a named check-run may or may not appear** — so treat the check-run poll as best-effort and fall through to
the comment-parsing path in step B once the review lands:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
HEAD_SHA=$(gh pr view <PR_NUMBER> --json headRefOid -q .headRefOid)
for i in $(seq 1 24); do            # ~4 min ceiling
  CHECK=$(gh api "repos/$REPO/commits/$HEAD_SHA/check-runs" \
    --jq '.check_runs[] | select(.name | test("greptile"; "i"))' 2>/dev/null)
  if [ -n "$CHECK" ] && [ "$(echo "$CHECK" | jq -r '.status')" = "completed" ]; then break; fi
  sleep 10
done
```

#### B. Fetch Greptile's review results

Greptile surfaces its score in several places — check all:

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh pr view <PR_NUMBER> --json body -q '.body'                                              # PR description
gh api --paginate "repos/$REPO/issues/<PR_NUMBER>/comments?per_page=100"                  # general comments
gh api "repos/$REPO/pulls/<PR_NUMBER>/reviews"                                            # reviews
```

Filter to `greptile-apps[bot]` and use the body from the most recently **updated** comment (`updated_at`),
not the most recently created — Greptile edits the same general comment each cycle. Parse the current body,
including the "Prompt to fix all with AI" section, before deciding there are no remaining issues.

Parse the text for the **confidence score** (`N/5`, e.g. `Confidence: 3/5`). Fetch unresolved inline
comments:

```bash
gh api "repos/$REPO/pulls/<PR_NUMBER>/comments"
```

Carry forward actionable items from the latest general Greptile comment even if the inline endpoint returns
zero.

**Re-anchoring gotcha:** on each re-review Greptile re-anchors its *existing* threads to the new HEAD and
marks threads on changed lines outdated/resolved, so a comment that surfaces after a push may be an old one
re-anchored, not a fresh finding. Two consequences: (a) the `N comments added` figure in the check-run
summary is **cumulative across all rounds**, not net-new since the last push; (b) before treating a comment
as new, cross-reference its `databaseId` against the previous round's thread list and compare `created_at`
vs `updated_at` — a `created_at` from a prior round means it is re-anchored, already addressed. Don't burn
an iteration "fixing" a finding you already fixed.

#### C. Check exit conditions

Stop the loop if **either**:
- Confidence is **5/5** AND there are **zero unresolved comments**, or
- Max iterations (5) reached — report the remaining state.

#### D. Fix actionable comments

For each unresolved Greptile comment: read the file in context, decide actionable (code change) vs
informational/false-positive, and fix the actionable ones. Keep fixes minimal and aligned to any project
invariants documented in `.greptile/`, `./AGENTS.md`, or `./CLAUDE.md`. Do **not** echo secrets or
sensitive data into any fix, reply, or commit.

#### E. Reply, then resolve threads

**Every comment gets a reply** (so Greptile learns and reviewers stay informed):
- Real fix → reply `Fixed in {sha}. {brief description}` and **leave the thread open** so a reviewer can
  verify.
- False positive / intentional → reply `Won't fix: {reason}` and **resolve** the thread.

Fetch unresolved threads and resolve the addressed/false-positive ones (see
[GraphQL reference](references/graphql-queries.md)); batch resolutions via aliases:

```bash
gh api graphql -f query='
mutation {
  t1: resolveReviewThread(input: {threadId: "ID1"}) { thread { isResolved } }
  t2: resolveReviewThread(input: {threadId: "ID2"}) { thread { isResolved } }
}'
```

#### F. Commit, push, loop

```bash
git add -A
git commit -m "address greptile review feedback (greploop iteration N)"
git push
sleep 5
```

Go back to **A**.

### 3. Report

| Field | Value |
|---|---|
| Iterations | N |
| Final confidence | X/5 |
| Comments resolved | N |
| Remaining comments | N (if any) |

If the loop exited on max iterations, list the remaining unresolved comments with file:line and suggest next
steps.

## Examples

**Example 1 — current branch, run the loop**
Input: `/greploop`
Output: detects the PR, posts `@greptileai review`, waits, fixes 4 actionable comments, resolves the
threads, pushes, re-reviews, and exits at 5/5 — reporting iterations + resolved count.

**Example 2 — explicit PR**
Input: `loop greptile on PR 42 until it's at 5/5`
Output: same loop targeting PR 42; if it stalls below 5/5 after 5 iterations, it reports the remaining
comments with `file:line` rather than looping forever.

## Error Handling

- **No Greptile check-run appears** → expected on some repos; fall through to the comment-parsing path in
  step B (PR body / general comment / reviews). Don't block waiting for a check-run that never posts.
- **Greptile already running** → don't post a duplicate `@greptileai review`; poll the existing run.
- **Score never reaches 5/5** → stop at 5 iterations and report remaining `file:line` items; never loop
  past the cap (runaway guard).
- **A finding is a false positive** → reply `Won't fix: {reason}` and resolve the thread; do not edit code
  to silence it.
- **Secret/sensitive data guardrail** → never echo secrets or project-sensitive values into a reply or
  commit message.

## Output format

```
Greploop complete.
  Iterations:    2
  Confidence:    5/5
  Resolved:      7 comments
  Remaining:     0
```

If not fully resolved:

```
Greploop stopped after 5 iterations.
  Confidence:    4/5
  Resolved:      12 comments
  Remaining:     2

Remaining issues:
  - src/handler.ts:45 — "bound this navigation timeout"
  - src/worker.ts:112 — "mark post_sent before the SQS delete"
```

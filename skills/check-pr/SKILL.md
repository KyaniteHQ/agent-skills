---
name: check-pr
description: Check a GitHub pull request for unresolved review comments (Greptile + human), failing status checks, and an incomplete description, then categorize each issue as actionable or informational and optionally fix, push, and resolve the threads. Use when the user wants to check a PR, triage review feedback, or get a PR ready before merge. Distinct from /greploop (which loops a fresh Greptile review to a 5/5 score) and babysit-pr (which shepherds the whole PR to squash-merge with the six CI gates). Trigger with "/check-pr", "/check-pr 42", "check the PR", "triage the review comments", or "is this PR ready to merge?".
license: MIT
version: "1.3"
author: greptileai (adapted)
compatibility: Requires git and gh (GitHub CLI) installed and authenticated.
allowed-tools: Bash(gh:*) Bash(git:*)
---

# Check PR

## Overview

A **one-shot** checker for a GitHub pull request: it reads the PR's review comments, status checks, and
description, classifies each issue as actionable / informational / already-addressed, and optionally fixes,
pushes, and resolves the threads. Use it for a single triage pass. For an iterate-until-clean loop against
Greptile use `/greploop`; to drive a PR all the way to squash-merge (with the six CI gates) use `babysit-pr`.

Adapted from [greptileai/skills](https://github.com/greptileai/skills) (MIT) — trimmed to the GitHub path,
the `greptile-apps[bot]` reviewer, and a generic PII guardrail.

## Prerequisites

- `git` and `gh` (GitHub CLI) installed and authenticated (`gh auth status`).
- An open PR for the branch (or pass a PR number explicitly).
- Greptile (`greptile-apps[bot]`) installed on the repo if you want its findings (advisory only).

## Contents

- [Inputs](#inputs)
- [Instructions](#instructions) — 1. Identify · 2. Fetch · 3. Wait for checks · 4. Analyze · 5. Categorize · 6. Report · 7. Fix · 8. Resolve threads
- [Examples](#examples)
- [Error Handling](#error-handling)
- [Output format](#output-format)

## Inputs

- **PR number** (optional): if not provided, detect the PR for the current branch.

## Instructions

### 1. Identify the PR

If a number was provided, use it. Otherwise detect it:

```bash
gh pr view --json number -q .number
```

### 2. Fetch PR details

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
gh pr view <PR_NUMBER> --json title,body,state,reviews,comments,headRefName,statusCheckRollup
gh api repos/$REPO/pulls/<PR_NUMBER>/comments
gh api --paginate "repos/$REPO/issues/<PR_NUMBER>/comments?per_page=100"
```

GitHub PRs are also issues, so general PR comments live on the issue-comments endpoint. **Greptile
(`greptile-apps[bot]`) edits a single general PR comment on each review cycle** instead of posting a new
one — always inspect the latest Greptile-authored general comment by `updated_at`, including any "Prompt to
fix all with AI" section, before concluding the PR is clear.

### 3. Wait for pending checks

Before analyzing, ensure all status checks have completed. If any are `PENDING`/`IN_PROGRESS`, poll
`statusCheckRollup` from `gh pr view` every 30s until all checks reach a terminal state. Note: Greptile's
review is advisory (`COMMENTED`), not a required check — the merge gate is determined by the
repo's required status checks (discover via `gh pr checks <PR_NUMBER>`).

### 4. Analyze the PR

Once checks are complete, evaluate:

- **A. Status checks** — are all CI checks passing? If failing, which, and why (`gh run view --log-failed`)?
  Discover check names at runtime via `gh pr checks <PR_NUMBER>`.
- **B. PR description** — complete? Issue tracker refs present? Any TODO/placeholder?
- **C. Review comments** — inline comments from `greptile-apps[bot]` and human reviewers
  (`gh api repos/$REPO/pulls/<PR_NUMBER>/comments`).
- **D. General comments** — the edited Greptile summary (use `updated_at`; parse "Prompt to fix all with
  AI"). Bot comments (e.g. `linear-code[bot]`) are informational.

### 5. Categorize issues

| Category | Meaning |
|---|---|
| **Actionable** | Code changes, test improvements, or fixes needed |
| **Informational** | Verification notes, questions, or FYIs that don't require changes |
| **Already addressed** | Resolved by a subsequent commit |

### 6. Report findings

Present a summary table:

| Area | Issue | Status | Action Needed |
|------|-------|--------|---------------|
| Status Checks | lint failing | Failing | Fix type error in `worker.py` |
| Review | "return error, don't raise" — greptile | Actionable | Switch raise → returned value |
| Description | missing issue ref | Actionable | Add issue tracker ref to body |

### 7. Fix issues (if requested)

If there are actionable items:

1. Switch to the PR's branch if not already on it.
2. Ask the user whether to fix.
3. If yes, make the fixes, run the offline gate, then commit and push:
   ```bash
   git add <files>
   git commit -m "address review feedback"
   git push
   ```

**PII/secrets guardrail:** never write a raw secret value or PII token into a commit message, PR body, or
comment reply. Keep fixes minimal and aligned to the project's rules (read `./AGENTS.md` or `./CLAUDE.md`
if present; otherwise apply generic code-quality conventions).

### 8. Resolve review threads

After addressing comments, resolve the corresponding threads. Fetch unresolved thread IDs (paginate if
needed — see [the GraphQL reference](references/graphql-queries.md)):

```bash
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
OWNER=${REPO%%/*}
REPONAME=${REPO##*/}
gh api graphql -f query='
query($cursor: String) {
  repository(owner: "'"$OWNER"'", name: "'"$REPONAME"'") {
    pullRequest(number: PR_NUMBER) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { id isResolved comments(first: 1) { nodes { body path } } }
      }
    }
  }
}'
```

If `hasNextPage` is true, repeat with `-f cursor=ENDCURSOR`. Then resolve addressed/informational threads,
batching multiple resolutions into one mutation via aliases (`t1`, `t2`, …):

```bash
gh api graphql -f query='
mutation {
  t1: resolveReviewThread(input: {threadId: "ID1"}) { thread { isResolved } }
  t2: resolveReviewThread(input: {threadId: "ID2"}) { thread { isResolved } }
}'
```

## Examples

**Example 1 — current branch**
Input: `/check-pr`
Output: detects the PR for the branch, reports `offline-gate` failing + 2 actionable Greptile comments,
asks before fixing, then (on yes) fixes, pushes, and resolves the addressed threads.

**Example 2 — explicit PR, read-only triage**
Input: `check PR 42 but don't change anything yet`
Output: the summary table only (no commits) — actionable vs informational, with recommended next steps.

## Error Handling

- **No PR found for the branch** → report it and ask for a PR number; do not guess.
- **`gh` not authenticated** → surface `gh auth status` and stop (don't proceed with partial data).
- **Checks still pending** → poll `statusCheckRollup` every 30s until terminal; never analyze mid-flight.
- **Greptile comment edited in place** → always read the latest general comment by `updated_at`; a stale
  read can miss the "Prompt to fix all with AI" section and wrongly conclude the PR is clear.
- **Thread resolve fails / comment is not threadable** → record it in the summary and move on; do not retry
  in a loop.

## Output format

Summarize: PR title + state; status checks (passing/failing/pending); total issues found; actionable items;
items safe to ignore (with reasons); recommended next steps.

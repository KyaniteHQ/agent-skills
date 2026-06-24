---
name: greptile-cli
description: Run and manage local Greptile code reviews from the terminal with the `greptile` CLI (v3.1.1) — review the current branch against a base branch before opening a PR, and configure/sign-in the CLI. Covers every command (review, review show, login, logout, whoami, settings, update) and all review flags. Use when the user wants a local Greptile review, to review a branch before the PR, to set CLI defaults, sign in/out, or check which account/org the CLI uses. Distinct from /greploop and /check-pr (which drive the Greptile GitHub App on an open PR) — this is the pre-PR local terminal surface that babysit-pr uses in its §1 loop. Trigger with "/greptile-cli", "run a greptile review", "review my branch locally before the PR", "greptile review", or "configure the greptile CLI".
license: MIT
version: "1.0"
compatibility: Requires the greptile CLI (npm i -g greptile; v3.1.1) authenticated (greptile login) and the repo indexed by Greptile (GitHub App installed on the repo).
allowed-tools: Bash(greptile:*) Bash(git:*) Bash(tmux:*)
---

# Greptile CLI

## Overview

The `greptile` CLI runs **local** Greptile code reviews from the terminal: it reviews the unmerged commits
on the current branch against a base branch, **before a PR exists**. This is the pre-PR / shift-left surface
— `babysit-pr` §1 uses it. It is distinct from `/greploop` and `/check-pr`, which drive the Greptile
**GitHub App** on an already-open PR. The CLI is **advisory**: the merge gate is determined by the project's
CI checks, not Greptile. Greptile applies the repo rules in `.greptile/` (config.json + rules.md) during the
review, so a CLI review enforces project-specific invariants on top of generic bugs.

## Prerequisites

- CLI installed + authenticated: `greptile login` (browser) or `greptile login --api-key` (headless/CI,
  reads the key from a prompt or stdin). Confirm with `greptile whoami`.
- The repo must be **indexed** by Greptile (the GitHub App is installed on the current repo — confirm with `gh repo view --json nameWithOwner -q .nameWithOwner` and check the Greptile dashboard).
- Run from the **repo root**, on a branch with **committed** commits — the CLI reviews committed commits vs
  the base and **ignores uncommitted changes** (commit first).

## Contents

- [Commands](#commands) — review · review show · login · logout · whoami · settings · update
- [review flags](#review-flags)
- [Recommended usage (agents / this repo)](#recommended-usage-agents--this-repo)
- [Examples](#examples)
- [Error Handling](#error-handling)
- [Output](#output)

## Commands

| Command | What it does |
|---|---|
| `greptile review [options]` | Review the current branch against its base (default branch unless `-b`). |
| `greptile review show [id]` | Re-open a previous review (most recent if no `id`). |
| `greptile login [--api-key]` | Sign in — browser by default; `--api-key` reads a key from prompt/stdin (headless/CI). |
| `greptile logout` | Sign out on this device. |
| `greptile whoami` | Show the signed-in account and organizations. |
| `greptile settings …` | View/change saved CLI defaults (see below). |
| `greptile update` | Update the CLI to the latest version. |
| `greptile --version` / `-V` | Print the CLI version. |

### review flags

| Flag | Purpose |
|---|---|
| `-b, --branch <BRANCH>` | Base branch to review against (omit → repo default, usually `main`). |
| `--resume` | Continue the latest unfinished review for this repo. |
| `--include <paths...>` | Include files Greptile holds back as sensitive (e.g. `--include .env config/db.pem`). Use sparingly — never include real secrets here. |
| `--json` | Print review comments as JSON (machine-parseable). |
| `--text` | Plain text (the default when output is piped). |
| `--agent` | Plain output for AI agents — alias for `--text`. Prefer this when an agent parses the result. |
| `--layout <comments\|diff>` | How findings are laid out (default `comments`). |
| `--diff` | Show findings beside the relevant code — shorthand for `--layout diff`. |
| `--context <LINES>` | Lines of nearby code around findings (default `15`). |
| `--width <COLUMNS>` / `--color` / `--no-color` | Output formatting. |

### settings

`greptile settings` persists CLI defaults (so you don't pass the same flags every time):

| Subcommand | Use |
|---|---|
| `settings list` | Show every setting and where its value comes from. |
| `settings get <key>` | Effective value of one setting. |
| `settings set <key> <value>` | Save a default, e.g. `greptile settings set review.layout diff`. |
| `settings unset <key>` | Remove a saved setting (revert to the built-in default). |
| `settings path` | Print where settings are stored. |

Keys: `color`, `review.output` (`auto`\|`text`\|`json`), `review.layout` (`comments`\|`diff`),
`review.context` (lines), `review.width` (columns).

## Recommended usage (agents / this repo)

- **Pre-PR review on a slice:** from the repo root, on the committed slice branch:
  `greptile review -b main --agent` — parse the findings, fix high-confidence correctness/invariant hits.
- **Long reviews → run in tmux** so they survive and stream live (the review is a cloud call that can take
  a minute or two):
  ```bash
  tmux new-session -d -s grept "greptile review -b main --agent 2>&1 | tee /tmp/greptile-review.out; echo ===DONE_\$?==="
  # poll:
  tmux capture-pane -t grept -p | tail -40        # or: tail -f /tmp/greptile-review.out
  ```
- **Headless / CI auth (no browser):** `greptile login --api-key` reads the key from stdin — pipe it in
  from `GREPTILE_API_KEY` (store in your secret manager / shell env); never print the value.
- **Guardrails:** advisory only (CI is the gate); never `--include` a real credential or the project's
  secrets/PII.

## Examples

**Example 1 — local review before opening a PR**
Input: `run a greptile review of my branch against main`
Output: `greptile review -b main --agent`, then a triaged summary — high-confidence fixes applied, false
positives noted, gate re-run.

**Example 2 — set a default + re-open a past review**
Input: `make greptile show findings next to the code by default, then reopen my last review`
Output: `greptile settings set review.layout diff` then `greptile review show`.

## Error Handling

- **`Not signed in`** → `greptile login` (or `--api-key` headless); verify `greptile whoami`. Don't proceed.
- **`command not found: greptile`** → installed under a global bin not on PATH; find it with
  `$(npm prefix -g)/bin/greptile` or `which greptile` after install — run `rehash` (zsh) or use the full path.
- **Repo not indexed / review stalls** → confirm the GitHub App is installed and the repo is indexed in the
  Greptile dashboard; a first-time index can take a while. Run the review in tmux and poll rather than
  blocking.
- **No commits to review** → the CLI reviews committed commits vs base and ignores the working tree; commit
  first. Use `-b main` explicitly if the default base is wrong.
- **`-b main` diffs against the LOCAL `main` ref** (not `origin/main`). If local `main` lags the remote,
  the review pulls in already-merged work and reports findings outside your branch (observed: a slice review
  surfaced findings from an already-merged PR because local `main` was behind). Sync first
  (`git fetch origin main:main`, or `git checkout main && git pull`) so the review covers only your branch's
  commits.

## Output

Summarize: base branch reviewed against, confidence/score if shown, the findings (actionable vs
informational) with `file:line`, what was fixed, and recommended next steps. Greptile stays advisory — the
project's CI gates remain the merge gate.

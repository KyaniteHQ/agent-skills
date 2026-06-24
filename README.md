# agent-skills

KyaniteHQ's reusable agent harness — a single versioned source for the [Agent Skills](https://code.claude.com/docs/en/skills),
agent templates, and orchestration contracts shared across projects and across harnesses (Claude
Code, Codex, opencode). Everything here is **project-agnostic**: skills infer the repo, CI checks,
and project rules from their environment (`gh repo view`, `gh pr checks`, the host project's own
`AGENTS.md` / `CLAUDE.md`) rather than hardcoding any one project.

## Layout

```
skills/          one dir per skill (SKILL.md + its scripts/references)
agents/          generic implementer / reviewer templates (.md for Claude, .toml for Codex)
orchestration/   shared JSON contracts + validators, the plan-bounce Workflow, agent-team notes
docs/            third-party-skills.md (re-install list for skills NOT vendored here)
.claude-plugin/  marketplace.json (install index)
```

## Skills

| Skill | What it does |
|---|---|
| [`babysit-pr`](skills/babysit-pr/) | Shepherd a slice's squash-merge PR to `main` end-to-end: pre-PR quality loop, open with a reviewer-ready description, poll CI gates, delegate the Greptile loop, fix, squash-merge when green. |
| [`greploop`](skills/greploop/) | Iteratively drive a PR to a clean Greptile review (5/5, zero unresolved comments). Adapted from `greptileai/skills` (MIT). |
| [`check-pr`](skills/check-pr/) | One-shot triage of a PR: unresolved comments, failing checks, incomplete description; optionally fix, push, resolve. Adapted from `greptileai/skills` (MIT). |
| [`greptile-cli`](skills/greptile-cli/) | Run and manage local Greptile reviews from the terminal — review a branch before opening a PR. |
| [`pr-review-canvas`](skills/pr-review-canvas/) | Render an interactive HTML PR-review walkthrough: core vs mechanical changes, reviewer annotations, moved-code detection. |
| [`adversarial-plan-bounce`](skills/adversarial-plan-bounce/) | Adversarially grade a plan with Codex as a second model (0-100, structural blockers, held decisions). v1 = one round; v2 loops to convergence. |
| [`metric-gated-refactor`](skills/metric-gated-refactor/) | Metric-gated refactoring loop for **Python**: requires a measured signal (radon CC + grimp/Louvain) AND a named problem before any change. |
| [`to-slices`](skills/to-slices/) | Decompose a plan/PRD into a VALIDATED DAG of vertical slices behind a Kahn + antichain + layer-rank gate. *Orchestration bundle.* |
| [`slice-conductor`](skills/slice-conductor/) | Execute a validated slice DAG end-to-end as an agent-team lead (worktree per slice, implement→review→fix→merge→ship). *Orchestration bundle.* |
| [`inspect-site`](skills/inspect-site/) | Live-site reconnaissance via chrome-devtools MCP — observe real endpoints, payload shapes, DOM, console; every claim tagged with a truth level. |
| [`image-gen`](skills/image-gen/) | Generate/edit images via ChatGPT's `image_generation` tool (gpt-image-2), authenticating with Codex/ChatGPT OAuth — no API key needed. |

## Install

### As a marketplace (per-skill, namespaced)

In Claude Code:

```
/plugin marketplace add KyaniteHQ/agent-skills
/plugin install babysit-pr@kyanite-skills
```

Marketplace installs are namespaced — `babysit-pr@kyanite-skills` becomes `/babysit-pr:babysit-pr`.
Run `/plugin marketplace update` to pull the latest.

### As the whole harness (recommended)

The orchestration trio (`to-slices`, `slice-conductor`, the `agents/` templates, and
`orchestration/`) is a **coupled bundle** — those skills resolve their contracts and agent
templates by relative path, so they need the full tree, not a standalone per-skill install. Clone
the repo and point your harness at it:

```bash
git clone https://github.com/KyaniteHQ/agent-skills.git
# then symlink skills/* into ~/.claude/skills and ~/.codex/skills
```

A single skill install (marketplace) is fine for the self-contained skills (`babysit-pr`,
`greploop`, `check-pr`, `greptile-cli`, `pr-review-canvas`, `adversarial-plan-bounce`,
`metric-gated-refactor`, `inspect-site`, `image-gen`); reach for the full clone when you want the
slice orchestration.

## Configuring the orchestration skills

`to-slices` / `slice-conductor` carry **no project constants** — the layer taxonomy, shared-core
file list, package prefix, and gate command are supplied at runtime via a project config that
matches [`orchestration/project-config.schema.json`](orchestration/project-config.schema.json).
See [`orchestration/sample-project-config.json`](orchestration/sample-project-config.json) for the
shape. Pass it with `--config <path>` or the `HARNESS_PROJECT_CONFIG` env var; with neither, the
validator degrades to a zero-config mode (acyclicity + collision checks only) and warns loudly.

## Third-party skills

This repo holds **only KyaniteHQ-authored skills**. Downloaded third-party skills are managed
separately by the [`skills`](https://github.com/mattpocock/skills) CLI and auto-update from
upstream — see [`docs/third-party-skills.md`](docs/third-party-skills.md) for the re-install list.

## Attribution

`greploop` and `check-pr` are customized forks of [`greptileai/skills`](https://github.com/greptileai/skills)
(MIT); `to-slices` is conceptually derived from `mattpocock/skills`' `to-issues`. See
[`NOTICE`](NOTICE). Everything is MIT-licensed — see [`LICENSE`](LICENSE).

---
name: adversarial-plan-bounce
description: >-
  Brutally/adversarially review a plan file with Codex as a second model -- Codex scores it 0-100
  against the live repo and returns structural blockers + named held decisions. v1 runs ONE scoring
  round; v2 (loop mode) drives a Workflow that bounces -> maximizes the plan -> re-bounces until the
  plan converges (EXECUTE / SHIP-AS-IS / NEEDS-HUMAN). Use when the user says "brutally review this
  plan", "score from 0 to 100", "bounce this with Claude", "re iterate", "loop until it converges",
  "maximize this plan", or asks to stress-test / get a second model to grade a plan in ~/.claude/plans.
  Review-only on repo code; loop mode edits only the plan file. Trigger with "brutally review this
  plan", "score this plan 0-100", "bounce this plan with Codex", "loop-bounce this plan to done".
compatibility: Requires the Codex CLI (`codex`) logged in on a gpt-5-family model; runs `uv run python` + `bash`; loop mode (v2) calls the Workflow tool (`plan-bounce-loop`). Reads run artifacts under .claude/plan-bounce/.
allowed-tools: Bash(uv:*) Bash(bash:*) Read Edit Write Workflow
---

# adversarial-plan-bounce

Get a second model (Codex) to adversarially grade an implementation plan against the live repo. Two
modes:

- **v1 -- one round** (the default cheap path): run the scoring command once, report, stop.
- **v2 -- recursive loop** (Workflow-orchestrated): bounce -> auto-maximize the plan -> re-bounce,
  accumulating open items in a ledger and auto-stopping at convergence. Reach for it when the user
  wants the plan driven *to* execute-ready, not just scored once.

## When to use

Trigger phrases: "brutally review this plan", "score from 0 to 100", "bounce this with Claude",
"re iterate", "give pasteable feedback for Claude", or any request to stress-test / second-model a
plan (usually a file in `~/.claude/plans/`).

## Requirements

- `codex --version` must work (Codex CLI logged in via ChatGPT or API key).
- The scoring leg uses `codex exec --output-schema`, which only works on a **gpt-5-family,
  non-`codex-*` model**. The driver resolves the model from `~/.codex/config.toml` (currently
  `gpt-5.5`); override with `--model` if needed.

## Inputs

- Plan path (required), e.g. `~/.claude/plans/foo.md`.
- Repo root (default: current directory) -- the repo the plan is verified against.
- Target score (default 95), scope (default "full plan", e.g. "Slices 0-2 only"), focus (optional).

If invoked with a **Linear URL or issue ID** instead of a plan path (e.g.
`/adversarial-plan-bounce https://linear.app/.../TEAM-42/...`): there is no plan file yet, so first
fetch the issue (and its comments), write the implementation plan to `~/.claude/plans/<issue-slug>.md`,
then run the round against that file. Derive the slug from the issue (e.g. `team-42-add-retry-logic`).

## Run one scoring round

> **v1 = ONE round.** The command below runs once, reports, and stops. Do NOT hand-loop it (revise
> the plan and re-run the bash command yourself) -- that is exactly what **v2 (the Workflow loop,
> below)** is for, and it carries the accumulated ledger + auto-stop the hand loop lacks. A user
> "re iterate" without asking to loop is one more single v1 round; "loop until it converges" /
> "maximize this plan to done" is v2.

Derive the slug from the plan filename (basename without `.md`), then:

```bash
uv run --with jsonschema python \
  "${CLAUDE_SKILL_DIR:-.claude/skills/adversarial-plan-bounce}/scripts/bounce_codex.py" \
  --plan <plan-path> \
  --repo "$(pwd)" \
  --iteration 1 \
  --workspace ".claude/plan-bounce/<slug>" \
  --target-score 95 \
  --scope "full plan"
```

The driver:

- snapshots the plan and renders the adversarial prompt into
  `.claude/plan-bounce/<slug>/iteration-001/`,
- runs Codex read-only (`--sandbox read-only`, `--ephemeral`) with the JSON output schema, passing the
  prompt via stdin (no shell redirection),
- validates the returned `codex-review.json` against the schema (fails loudly if malformed),
- writes a compact `score.json` and prints a summary.

Extra flags: `--codex-bin` (default `codex`), `--max-attempts` (default 3), `--timeout-seconds`
(default 1200, per attempt), `--model` (override the resolved model).

## Self-healing

The driver auto-recovers bounded runtime failures and logs every action to
`iteration-NNN/self-heal.log`:

- **empty / missing output** (codex exit-0 trap) -> deletes any stale review, retries up to
  `--max-attempts`;
- **invalid JSON / schema violation** -> feeds the exact error back into the next attempt's prompt
  (repair) and re-runs;
- **hang** -> per-attempt `--timeout-seconds` kills and retries;
- **score/verdict band mismatch** -> recomputes the canonical verdict from the score band and
  overrides it (`done` depends only on score + blockers + execution_mode, never on the verdict);
- **incompatible configured model** -> falls back to `gpt-5.5` (an explicit incompatible `--model`
  stays a hard error).

After a run, if `self-heal.log` is non-empty, read it and `references/runtime-notes.md`:

- transient and recovered -> just report what self-healed;
- **could not auto-recover** (failed all attempts, or a brand-new symptom) -> diagnose, apply the
  smallest fix to the skill (prompt/schema/driver) as a **visible diff**, and append a
  `symptom -> cause -> fix` row to `references/runtime-notes.md`. Never silently rewrite the driver.

Deterministic check of the self-heal paths (no real Codex call):
`bash "${CLAUDE_SKILL_DIR:-.claude/skills/adversarial-plan-bounce}/scripts/selftest.sh"`.

## Report

Read `iteration-001/score.json` and `iteration-001/codex-review.json` and report to the user:

- score + verdict, and whether `done` (score >= target AND no structural blockers AND
  `execution_mode_clear`),
- each structural blocker with its recommendation,
- high/critical findings,
- named held decisions.

## Downstream (feed the result into implementation + the PR)

`codex-review.json` is not throwaway. Its `structural_blockers` and `held_decisions` are a
durable acceptance checklist: carry them into the implementation and the pre-PR review.
Design-time blockers reliably predict what the PR reviewer (Greptile) flags later -- e.g. a
"launch-failure / cancellation path uncovered" blocker tends to resurface as the reviewer's P1s
-- so closing each one before opening the PR prevents review churn. `babysit-pr` re-reads this
artifact in its pre-PR loop, so leave it where the driver wrote it (`.claude/plan-bounce/<slug>/`).

## Guardrails

- **Review-only.** Never edit source/config/test files from this skill. The Codex leg runs in a
  read-only sandbox so it cannot mutate the repo while verifying claims.
- The only writes are the run artifacts under `.claude/plan-bounce/<slug>/` (gitignored).

## v2: recursive loop (Workflow-orchestrated)

When the user wants the plan driven *to* execute-ready -- "loop until it converges", "maximize this
plan to done", "iterate this to 95", or a plan-mode `plan -> bounce -> maximize -> approve` in one step
-- run the **`plan-bounce-loop` Workflow** instead of the v1 command. (Invoking this skill in loop mode
is the explicit Workflow opt-in.) Call the Workflow tool:

```
Workflow({ name: 'plan-bounce-loop', args: {
  plan: '<absolute plan path under ~/.claude/plans/>',
  repo: '<repo root, e.g. the current project directory>',
  scope: 'full plan',            // optional
  target: 95,                    // optional
  maxRounds: 6,                  // optional
  improveDelta: 3,               // optional (min score gain that counts as "improving")
} })
```

Each round the Workflow runs **two agents**: a *bounce* agent (runs `bounce_codex.py`, returns the
parsed review) and a *maximize* agent (edits **only the plan file** to fold in every open structural
blocker + critical/high finding). Between rounds it keeps an **accumulated ledger** (so a blocker fixed
in round 2 cannot silently reappear in round 4) and auto-detects convergence.

**Stop rules** (both success terminals require `execution_mode_clear=true`):

- **EXECUTE** -- `done`: score >= target AND 0 structural blockers AND `execution_mode_clear`.
- **SHIP-AS-IS** -- executable AND score plateaued (< `improveDelta` gain for >=2 rounds) AND 0 open
  structural blockers AND 0 open high/critical findings. Remaining surface = held decisions (yours to resolve).
- **NEEDS-HUMAN** -- score regressed over the last 2 rounds, OR an item stayed open >=3 rounds
  (whack-a-mole), OR plateaued with `execution_mode_clear=false`, OR `maxRounds` reached with blockers
  open. The loop hands the accumulated ledger back; do not keep grinding.

The Workflow returns a `FINAL_SCHEMA` object: `recommendation`, `trajectory` (the score path),
`final_score`/`final_verdict`/`final_done`, `execution_mode_clear`, `open_items`, `held_decisions`,
`artifacts_dir`, `plan_path`. Relay it to the user as an ASCII-arrow trajectory + the recommendation +
the open items / held decisions. **Never auto-execute** a converged plan -- the loop ends at the report
and the user's approval gate.

**Loop guardrails:** the maximize step edits ONLY the plan file under `~/.claude/plans/` (the same
artifact a human maximizes by hand) -- never repo source/config/tests. The Codex leg stays
`--sandbox read-only`. The only repo writes are the gitignored artifacts under `.claude/plan-bounce/`.

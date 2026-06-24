# Runtime notes (self-heal knowledge base)

Durable record of failure modes this skill has hit and how they are handled. The driver
(`scripts/bounce_codex.py`) auto-handles the rows marked **auto**; the agent handles **manual** rows
by reading the run's `self-heal.log`, applying a surfaced fix, and appending a new row here.

Format per entry: `symptom -> cause -> fix (auto|manual)`.

## Known failure modes

- **codex writes the file but it is empty / missing** -> codex exited 0 without producing output (the
  exit-0 trap; transient API/runtime hiccup) -> **auto**: driver deletes any stale review before each
  attempt and retries up to `--max-attempts`.
- **codex output is not valid JSON, or violates the schema** -> model emitted prose or a malformed /
  off-spec object -> **auto**: driver feeds the exact validation error back into the next attempt's
  prompt ("repair") and re-runs.
- **codex hangs / takes too long** -> high reasoning effort or a stuck process -> **auto**: per-attempt
  `--timeout-seconds` (default 1200) kills it; the attempt is retried.
- **score/verdict band mismatch** (e.g. score 88 with verdict "agreed") -> model mis-banded its own
  score -> **auto**: driver recomputes the canonical verdict from the score band, overrides it, and
  notes the correction. `done` never depends on `verdict`, only on score + blockers + execution_mode.
- **configured model can't use --output-schema** (a `codex-*` or non-gpt-5 model; codex bug #4181) ->
  wrong default in `~/.codex/config.toml` -> **auto**: driver falls back to `FALLBACK_MODELS[0]`
  (`gpt-5.5`) and notes it. An explicit incompatible `--model` is a hard error (the user was explicit).
- **the fallback model itself fails with a model-not-found error** (e.g. `404 unknown model: "gpt-5.5"`
  on a proxy) -> single-deep fallback dead-ended in a live run -> **auto**: driver rotates through the
  `FALLBACK_MODELS` chain (`gpt-5.5 -> gpt-5.1 -> gpt-5`), but ONLY on an explicit model-level stderr
  signature (`unknown model` / `model not found` / `invalid model`). A plain exit-0-trap / empty output
  is NOT treated as a model failure (that would hide prompt/runtime/API errors behind model churn) --
  it stays the hard `RuntimeError` above. An explicit `--model` never rotates.
- **`codex` not found / not logged in** -> CLI missing or unauthenticated -> **manual**: install/login
  (`codex --version`, `codex login`); cannot be auto-fixed safely.
- **the loop oscillates / never reaches the target** (v2 only; e.g. `46 -> 72 -> 42 -> 74`) -> a plan
  revision fixes some blockers but exposes new ones, or Codex's score is non-deterministic -> **auto**:
  the `plan-bounce-loop` Workflow keeps an accumulated ledger (an item open across >=3 rounds is
  whack-a-mole) and stops at **NEEDS-HUMAN** on a net regression over the last 2 rounds rather than
  chasing 95 -- it hands the accumulated open set back to the owner.

## How the agent extends this file

When a run's `self-heal.log` shows a failure the driver could NOT auto-recover (failed all attempts, or
a brand-new symptom), diagnose it, apply the smallest fix to the skill (prompt/schema/driver) as a
visible diff, and append a new `symptom -> cause -> fix` row above. Never silently rewrite the driver.

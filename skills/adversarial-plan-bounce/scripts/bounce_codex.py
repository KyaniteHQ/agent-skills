"""Adversarial plan-bounce: one self-healing Codex scoring round over a plan markdown file.

Renders an adversarial review prompt from the plan, runs `codex exec` with a JSON output schema
(read-only sandbox, ephemeral session), and self-heals bounded runtime failures: it retries on
empty/timeout, repairs on invalid-JSON / schema-violation by feeding the error back to Codex, falls
back to a safe model when the configured one cannot use --output-schema, and fixes a score/verdict
band mismatch. Every recovery action is logged to the iteration's `self-heal.log`. This is the v1
scoring leg; the running agent runs any revision loop on top of it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import jsonschema

SKILL_DIR: Final[Path] = Path(__file__).resolve().parent.parent
SCHEMA_PATH: Final[Path] = SKILL_DIR / "schemas" / "plan-review.schema.json"
RUBRIC_PATH: Final[Path] = SKILL_DIR / "references" / "review-rubric.md"
CODEX_CONFIG_PATH: Final[Path] = Path.home() / ".codex" / "config.toml"
HIGH_SEVERITIES: Final[frozenset[str]] = frozenset({"critical", "high"})
STDERR_TAIL_CHARS: Final[int] = 2000
# Fallback chain tried in order when no explicit --model is given (single fallback dead-ended in a
# live run when gpt-5.5 itself 404'd on the proxy). The first entry is also the lone safe fallback.
FALLBACK_MODELS: Final[tuple[str, ...]] = ("gpt-5.5", "gpt-5.1", "gpt-5")
# Stderr signatures that prove a MODEL-level failure (a missing / incompatible model), as opposed to
# the generic exit-0 / empty-output trap. Only these trigger fallback-model rotation; a plain empty
# output stays a hard error so a prompt/runtime/API hiccup is never hidden behind model churn.
MODEL_LEVEL_FAILURE_RE: Final[re.Pattern[str]] = re.compile(
    r"unknown model|no such model|model not found|model_not_found|invalid[_ ]model", re.IGNORECASE
)
# (exclusive upper bound, verdict) bands; score at/above the last bound is "agreed".
VERDICT_BANDS: Final[tuple[tuple[int, str], ...]] = (
    (60, "unsafe"),
    (80, "not-executable"),
    (90, "blockers-remain"),
    (95, "approved-with-nits"),
)


def append_note(self_heal_path: Path, message: str) -> None:
    stamp = datetime.now(UTC).isoformat()
    with self_heal_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {message}\n")


def verdict_for_score(score: int) -> str:
    for upper_bound, verdict in VERDICT_BANDS:
        if score < upper_bound:
            return verdict
    return "agreed"


def _is_compatible_model(model: str) -> bool:
    # `--output-schema` only works on gpt-5-family, non-codex models (codex bug #4181).
    return model.startswith("gpt-5") and "codex" not in model


def resolve_model(explicit: str | None) -> tuple[str, str | None]:
    """Return (model, self_heal_note). An explicit but incompatible model is a hard error; an
    incompatible/missing config model self-heals to the fallback."""
    if explicit is not None:
        if not _is_compatible_model(explicit):
            raise RuntimeError(
                f"--model {explicit!r} cannot be used with --output-schema; "
                "use a gpt-5-family non-codex model, e.g. gpt-5.5"
            )
        return explicit, None
    fallback = FALLBACK_MODELS[0]
    if not CODEX_CONFIG_PATH.is_file():
        return fallback, f"no codex config at {CODEX_CONFIG_PATH}; using {fallback}"
    config = tomllib.loads(CODEX_CONFIG_PATH.read_text(encoding="utf-8"))
    model = config.get("model")
    if not isinstance(model, str) or not _is_compatible_model(model):
        note = f"config model {model!r} unusable with --output-schema; using {fallback}"
        return fallback, note
    return model, None


def _is_model_level_failure(message: str) -> bool:
    """True only on an explicit model-not-found / incompatible-model stderr signature -- never on a
    plain empty-output / exit-0 trap (a generic runtime hiccup, not a model problem)."""
    return MODEL_LEVEL_FAILURE_RE.search(message) is not None


def model_candidates(explicit: str | None, primary: str) -> list[str]:
    """Model try-order: an explicit --model is used alone (no rotation); otherwise the resolved
    primary first, then each remaining distinct fallback."""
    if explicit is not None:
        return [primary]
    unique: list[str] = []
    for model in (primary, *FALLBACK_MODELS):
        if model not in unique:
            unique.append(model)
    return unique


def extract_prev_blockers(prev_review_path: Path | None) -> str:
    """Render the prior iteration's blockers + high/critical findings for the prompt."""
    if prev_review_path is None:
        return "(none -- this is the first round)"
    review: dict[str, Any] = json.loads(prev_review_path.read_text(encoding="utf-8"))
    lines: list[str] = []
    for blocker in review.get("structural_blockers", []):
        lines.append(f"- [structural] {blocker['title']}: {blocker['why']}")
    for finding in review.get("findings", []):
        if finding.get("severity") in HIGH_SEVERITIES:
            lines.append(f"- [{finding['severity']}] {finding['title']}: {finding['body']}")
    if not lines:
        return "(prior round reported no structural blockers or high/critical findings)"
    return "\n".join(lines)


def render_prompt(
    plan_path: Path,
    plan_text: str,
    repo: Path,
    scope: str,
    focus: str,
    target: int,
    prev_blockers: str,
) -> str:
    template = RUBRIC_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{{PLAN_PATH}}", str(plan_path))
        .replace("{{PLAN_TEXT}}", plan_text)
        .replace("{{REPO}}", str(repo))
        .replace("{{SCOPE}}", scope)
        .replace("{{FOCUS}}", focus or "(no specific focus -- review the whole plan)")
        .replace("{{TARGET}}", str(target))
        .replace("{{PREV_BLOCKERS}}", prev_blockers)
    )


def build_codex_argv(codex_bin: str, repo: Path, model: str, review_out_path: Path) -> list[str]:
    return [
        codex_bin,
        "exec",
        "-C",
        str(repo),
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "-m",
        model,
        "--output-schema",
        str(SCHEMA_PATH),
        "-o",
        str(review_out_path),
        "-",
    ]


def run_codex(
    argv: list[str],
    prompt_path: Path,
    stdout_path: Path,
    stderr_path: Path,
    repo: Path,
    timeout_seconds: int,
) -> int:
    """Run codex with the prompt piped via stdin (argv list, no shell redirection)."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    with (
        prompt_path.open("rb") as prompt_fh,
        stdout_path.open("ab") as stdout_fh,
        stderr_path.open("ab") as stderr_fh,
    ):
        completed = subprocess.run(
            argv,
            stdin=prompt_fh,
            stdout=stdout_fh,
            stderr=stderr_fh,
            cwd=repo,
            env=env,
            check=False,
            timeout=timeout_seconds,
        )
    return completed.returncode


def _tail(path: Path) -> str:
    if not path.is_file():
        return "(no stderr captured)"
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-STDERR_TAIL_CHARS:]


def load_review(review_out_path: Path, stderr_path: Path) -> dict[str, Any]:
    """Read the codex output file; codex always exits 0, so the file is the real artifact.

    Raises RuntimeError (not a bare ValueError) on every failure mode so the caller's self-heal loop
    can classify and recover.
    """
    if not review_out_path.is_file() or review_out_path.stat().st_size == 0:
        raise RuntimeError(
            f"codex wrote no review to {review_out_path} (exit-0 trap). "
            f"stderr tail:\n{_tail(stderr_path)}"
        )
    text = review_out_path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"codex output at {review_out_path} is not valid JSON: {exc}") from exc


def validate_review(review: dict[str, Any], review_out_path: Path) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=review, schema=schema)
    except jsonschema.ValidationError as exc:
        raise RuntimeError(
            f"codex review at {review_out_path} failed schema validation: "
            f"{exc.message} (at path {list(exc.absolute_path)})"
        ) from exc


def compute_done(review: dict[str, Any], target: int) -> bool:
    return (
        review["score"] >= target
        and len(review["structural_blockers"]) == 0
        and review["execution_mode_clear"] is True
    )


def write_commands_log(path: Path, argv: list[str], prompt_path: Path, model: str) -> None:
    stamp = datetime.now(UTC).isoformat()
    body = (
        f"# {stamp}\n"
        f"model: {model}\n"
        f"command: {shlex.join(argv)} < {shlex.quote(str(prompt_path))}\n"
        "per-attempt exit codes and self-heal actions: see self-heal.log\n"
    )
    path.write_text(body, encoding="utf-8")


def write_score_json(path: Path, review: dict[str, Any], done: bool) -> None:
    score = {
        "score": review["score"],
        "verdict": review["verdict"],
        "n_blockers": len(review["structural_blockers"]),
        "execution_mode_clear": review["execution_mode_clear"],
        "done": done,
    }
    path.write_text(json.dumps(score, indent=2), encoding="utf-8")


def score_once_with_self_heal(
    base_prompt: str,
    iter_dir: Path,
    repo: Path,
    model: str,
    codex_bin: str,
    max_attempts: int,
    timeout_seconds: int,
    self_heal_path: Path,
) -> dict[str, Any]:
    """Run codex up to max_attempts, recovering from empty/timeout/invalid output, then self-correct
    a score/verdict band mismatch. Raises after the last attempt with the accumulated failures."""
    review_out_path = iter_dir / "codex-review.json"
    stdout_path = iter_dir / "codex-stdout.log"
    stderr_path = iter_dir / "codex-stderr.log"
    prompt_path = iter_dir / "prompt.md"
    argv = build_codex_argv(codex_bin, repo, model, review_out_path)
    repair_suffix = ""
    failures: list[str] = []

    for attempt in range(1, max_attempts + 1):
        # Drop any stale review so a codex failure can't be read as a prior success (exit-0 trap).
        review_out_path.unlink(missing_ok=True)
        prompt_path.write_text(base_prompt + repair_suffix, encoding="utf-8")
        for log_path in (stdout_path, stderr_path):
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n=== attempt {attempt} ===\n")

        try:
            returncode = run_codex(
                argv, prompt_path, stdout_path, stderr_path, repo, timeout_seconds
            )
        except subprocess.TimeoutExpired:
            failures.append(f"attempt {attempt}: timed out after {timeout_seconds}s")
            append_note(self_heal_path, f"attempt {attempt}: codex timed out -> retry")
            repair_suffix = ""
            continue

        if returncode != 0:
            append_note(self_heal_path, f"attempt {attempt}: codex exited non-zero ({returncode})")
        try:
            review = load_review(review_out_path, stderr_path)
            validate_review(review, review_out_path)
        except RuntimeError as exc:
            failures.append(f"attempt {attempt}: {exc}")
            if "wrote no review" in str(exc):
                action, repair_suffix = "retry", ""
            else:
                action = "repair"
                repair_suffix = (
                    "\n\nYOUR PREVIOUS OUTPUT WAS REJECTED. "
                    f"Reason: {exc}\nReturn ONLY corrected JSON matching the schema."
                )
            append_note(self_heal_path, f"attempt {attempt} failed ({action}): {exc}")
            continue

        canonical = verdict_for_score(review["score"])
        if review["verdict"] != canonical:
            append_note(
                self_heal_path,
                f"attempt {attempt}: corrected verdict {review['verdict']!r} -> "
                f"{canonical!r} for score {review['score']}",
            )
            review["verdict"] = canonical
            review_out_path.write_text(json.dumps(review, indent=2), encoding="utf-8")
        if attempt > 1:
            append_note(
                self_heal_path,
                f"attempt {attempt}: recovered after {attempt - 1} failed attempt(s)",
            )
        return review

    raise RuntimeError(
        f"codex failed after {max_attempts} attempts; see {self_heal_path}. "
        "Failures: " + " | ".join(failures)
    )


def summarize(review: dict[str, Any], done: bool, target: int) -> str:
    header = f"score: {review['score']}/100   verdict: {review['verdict']}   done: {done}"
    detail = (
        f"(target {target}, blockers {len(review['structural_blockers'])}, "
        f"execution_mode_clear {review['execution_mode_clear']})"
    )
    lines = [f"{header}  {detail}"]
    if review["structural_blockers"]:
        lines.append("\nstructural blockers:")
        for blocker in review["structural_blockers"]:
            lines.append(f"  - {blocker['title']}: {blocker['recommendation']}")
    high = [f for f in review["findings"] if f["severity"] in HIGH_SEVERITIES]
    if high:
        lines.append("\nhigh/critical findings:")
        for finding in high:
            lines.append(
                f"  - [{finding['severity']}] {finding['title']} -> {finding['recommendation']}"
            )
    if review["held_decisions"]:
        lines.append("\nheld decisions:")
        for decision in review["held_decisions"]:
            lines.append(f"  - {decision['decision']} (owner: {decision['owner']})")
    lines.append(f"\nsummary: {review['summary']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One self-healing Codex adversarial scoring round over a plan file."
    )
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--iteration", required=True, type=int)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--target-score", type=int, default=95)
    parser.add_argument("--scope", default="full plan")
    parser.add_argument("--focus", default="")
    parser.add_argument("--prev-blockers", type=Path, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=1200)
    args = parser.parse_args()

    plan_path = args.plan.expanduser().resolve()
    repo = args.repo.expanduser().resolve()
    if not plan_path.is_file():
        raise RuntimeError(f"plan file not found: {plan_path}")

    model, model_note = resolve_model(args.model)

    iter_dir = args.workspace.expanduser().resolve() / f"iteration-{args.iteration:03d}"
    iter_dir.mkdir(parents=True, exist_ok=True)
    self_heal_path = iter_dir / "self-heal.log"
    if model_note is not None:
        append_note(self_heal_path, f"model self-heal: {model_note}")
        print(f"[self-heal] {model_note}", file=sys.stderr)

    plan_text = plan_path.read_text(encoding="utf-8")
    shutil.copyfile(plan_path, iter_dir / "plan.md")

    prev_path = args.prev_blockers.expanduser().resolve() if args.prev_blockers else None
    prev_blockers = extract_prev_blockers(prev_path)
    base_prompt = render_prompt(
        plan_path, plan_text, repo, args.scope, args.focus, args.target_score, prev_blockers
    )

    candidates = model_candidates(args.model, model)
    review_out_path = iter_dir / "codex-review.json"
    argv = build_codex_argv(args.codex_bin, repo, candidates[0], review_out_path)
    write_commands_log(iter_dir / "commands.log", argv, iter_dir / "prompt.md", candidates[0])

    review: dict[str, Any] | None = None
    for idx, candidate in enumerate(candidates):
        try:
            review = score_once_with_self_heal(
                base_prompt,
                iter_dir,
                repo,
                candidate,
                args.codex_bin,
                args.max_attempts,
                args.timeout_seconds,
                self_heal_path,
            )
            if idx > 0:
                append_note(
                    self_heal_path, f"model rotation: recovered on fallback model {candidate!r}"
                )
            break
        except RuntimeError as exc:
            is_last = idx == len(candidates) - 1
            if is_last or not _is_model_level_failure(str(exc)):
                raise
            next_model = candidates[idx + 1]
            append_note(
                self_heal_path,
                f"model rotation: {candidate!r} hit a model-level failure; trying {next_model!r}. "
                f"cause: {str(exc).splitlines()[0]}",
            )
    assert review is not None  # the loop either set review or re-raised
    done = compute_done(review, args.target_score)
    write_score_json(iter_dir / "score.json", review, done)

    print(summarize(review, done, args.target_score))
    print(f"\nartifacts: {iter_dir}")
    if self_heal_path.is_file() and self_heal_path.stat().st_size > 0:
        print(f"self-heal actions were taken; see {self_heal_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

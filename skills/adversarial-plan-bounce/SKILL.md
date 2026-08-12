---
name: adversarial-plan-bounce
description: Red-team a grounded, implementation-ready plan with an independent critic. Use when Omer requests a plan bounce, repository policy requires cross-model review, or a high-impact architecture, migration, security, CI/CD, data, worktree, or ownership plan retains contested assumptions. Run after local evidence resolves first-draft questions and before implementation.
---

# Adversarial Plan Bounce

Use an independent model to test whether a plan proves its contract. Keep the active harness as the plan owner.

## Workflow

1. Ground the plan until each load-bearing claim is confirmed or marked uncertain.
2. Build the sanitized critic packet below. Include only evidence needed to test the contract.
3. Send the packet automatically to the external critic when its CLI is available.
4. Treat every returned finding as an unverified claim.
5. Adjudicate each finding against repository evidence or current primary sources.
6. Revise for accepted findings. Record rejected findings and owner decisions in the ledger.
7. Resume the same critic session with the revised packet and ledger.
8. Finish when the critic approves, or when evidence disproves every remaining blocker. Leave unresolved owner decisions open.

If resume fails, start a fresh critic with the prior critique and adjudication ledger. Record the resume failure when a run journal exists.

## Critic Packet

Use these headings:

```markdown
# Contract and success criteria
# Proposed plan
# Confirmed evidence and invariants
# Constraints and authority
# Uncertainty and unresolved owner decisions
# Adjudication ledger (follow-up only)
```

Remove secrets, credentials, raw headers, private infrastructure details, unnecessary logs, and unrelated source text. Complete the packet when it contains enough evidence to test the contract and is safe for external use.

The active harness owns sanitization. The adapters transport the packet verbatim.

The ledger records each finding ID, status (`accepted`, `rejected`, or `owner-decision`), supporting evidence, and resulting plan change.

## Optional Evidence Bundle

Use packet-only mode by default. Use an evidence bundle only when selected files are necessary to test a load-bearing claim.

1. Create a fresh private directory with `mktemp -d "${XDG_RUNTIME_DIR:-/tmp}/adversarial-plan-bounce-evidence.XXXXXX"`.
2. Copy only selected sanitized regular files into it. Keep all files private. Include no symlinks, sockets, devices, or repository metadata.
3. Run `scripts/codex_to_claude.sh --evidence-dir <directory> <packet-file>`.
4. Pass the same option to `scripts/codex_to_claude_resume.sh` when the follow-up needs file access.
5. Remove the temporary bundle after the last bounce, including failure paths.

The adapter revalidates the bundle on every call. It accepts only a private, non-Git directory under the active runtime root. Evidence mode requires `bubblewrap`. The operating-system sandbox mounts the bundle read-only and hides other user files. Claude receives only `Read`, `Glob`, and `Grep`. Bash, Web, edit tools, repository access, hooks, plugins, MCP, and skills remain unavailable.

The sandbox shares the host network because Claude must reach its API. Network isolation comes from the restricted tool surface and safe mode, not a network namespace. The adapter stores private session state under the runtime root so the same critic UUID can resume.

Keep the reverse Codex adapter packet-only. Codex CLI does not provide the same read-tool allowlist.

## Critic Contract

The critic returns schema-validated fields for:

- `verdict`: `approve`, `revise`, or `reject`
- `blockers`
- `risks`
- `missing_verification`
- `simpler_alternative`
- `plan_patch`

Each finding identifies the contract impact, failure scenario, evidence basis, verification status, and smallest useful plan change. The critic returns no numeric score.

Use `packet_supported` for packet evidence, `bundle_supported` for staged-file evidence, and `needs_verification` for evidence outside the critic boundary.

`approve` means no blocker remains. `revise` means bounded changes can close the blockers. `reject` means the core approach cannot safely prove the contract.

## Codex to Claude

1. Run `scripts/codex_to_claude.sh <packet-file>` or pass a closed pipe with `-`. Add `--evidence-dir <directory>` only for the optional evidence branch.
2. Read `critic_session_id`, `requested_model`, and `resolved_model` from the JSON result.
3. Store `critic_session_id` in the run manifest or journal when one exists.
4. Resume with `scripts/codex_to_claude_resume.sh <critic-session-id> <revised-packet-file>`. Put `--evidence-dir <directory>` before the session ID when the follow-up needs the bundle.

The adapter pins the critic family to `opus`. It does not inherit the interactive Claude model.

Claude can report `stop_reason: tool_use` for schema-constrained output. Use the adapter flags, permission denials, and server-tool counters to assess isolation instead.

## Claude to Codex

1. Run `scripts/claude_to_codex.sh <packet-file>` or pass a closed pipe with `-`.
2. Read `critic_session_id` from the first JSONL event.
3. Resume with `scripts/claude_to_codex_resume.sh <critic-session-id> <revised-packet-file>`.

## Failure Handling

- If the external CLI or external execution is unavailable, use the strongest practical local read-only critique path. State that cross-model review was unavailable.
- Keep the packet-only boundary if the critic requests tools, repository access, secrets, edits, or recursive skill use.
- Confirm external claims with local evidence or current primary sources before using them.

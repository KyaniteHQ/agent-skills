#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
source "$script_dir/_common.sh"

packet_source="${1:?usage: claude_to_codex.sh PACKET_FILE|-}"

# Keep this adapter packet-only until Codex can allowlist read tools without Bash.

apb_require_command codex
apb_require_command jq
apb_validate_packet_source "$packet_source"

critic_root="${XDG_RUNTIME_DIR:-/tmp}/adversarial-plan-bounce-codex-$UID"
install -d -m 700 -- "$critic_root"
result_file="$(mktemp)"
trap 'rm -f -- "$result_file"' EXIT

set +e
{
  printf '%s\n\n' "$APB_PACKET_SYSTEM_PROMPT" 'Assess this sanitized critic packet.' 'CRITIC PACKET:'
  apb_emit_packet "$packet_source"
} | (cd -- "$critic_root" && codex exec \
  -C "$critic_root" \
  --sandbox read-only \
  --skip-git-repo-check \
  --ignore-user-config \
  --ignore-rules \
  --output-schema "$APB_SCHEMA_FILE" \
  --json \
  -) \
  >"$result_file"
pipeline_status=("${PIPESTATUS[@]}")
set -e

(( pipeline_status[0] == 0 )) || apb_die "${pipeline_status[0]}" "failed to read critic packet"
(( pipeline_status[1] == 0 )) || apb_die "${pipeline_status[1]}" "codex critic failed with status ${pipeline_status[1]}"

apb_emit_codex_result "$result_file"

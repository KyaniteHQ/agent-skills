#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source-path=SCRIPTDIR
source "$script_dir/_common.sh"

evidence_source=""
if [[ "${1:-}" == "--evidence-dir" ]]; then
  [[ "$#" -ge 2 ]] || apb_die 64 "--evidence-dir requires a directory"
  evidence_source="${2:-}"
  shift 2
fi
[[ "$#" == 1 ]] || apb_die 64 "usage: codex_to_claude.sh [--evidence-dir DIRECTORY] PACKET_FILE|-"
packet_source="$1"

apb_require_command claude
apb_require_command jq
apb_require_command uuidgen
apb_validate_packet_source "$packet_source"
apb_claude_mode "$evidence_source"

critic_session_id="$(uuidgen | tr '[:upper:]' '[:lower:]')"
apb_prepare_claude_command "$critic_session_id"
schema_json="$(apb_schema_json)"
result_file="$(mktemp)"
trap 'rm -f -- "$result_file"' EXIT

set +e
{
  printf '%s\n\n' 'Assess this sanitized critic packet.' 'CRITIC PACKET:'
  apb_emit_packet "$packet_source"
} | (umask 077 && cd -- "$APB_CRITIC_ROOT" && "${APB_CLAUDE_COMMAND[@]}" -p \
  --session-id "$critic_session_id" \
  --model "$APB_CLAUDE_MODEL" \
  --safe-mode \
  --no-chrome \
  --tools "$APB_CLAUDE_TOOLS" \
  --disable-slash-commands \
  --effort high \
  --system-prompt "$APB_SYSTEM_PROMPT" \
  --output-format json \
  --json-schema "$schema_json" \
  ) \
  >"$result_file"
pipeline_status=("${PIPESTATUS[@]}")
set -e

(( pipeline_status[0] == 0 )) || apb_die "${pipeline_status[0]}" "failed to read critic packet"
(( pipeline_status[1] == 0 )) || apb_die "${pipeline_status[1]}" "claude critic failed with status ${pipeline_status[1]}"

apb_annotate_claude_result "$result_file" "$critic_session_id" "$APB_CRITIC_MODE"

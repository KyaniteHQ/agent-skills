#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
skill_dir="$(cd -- "$script_dir/.." && pwd)"
test_root="$(mktemp -d)"
fake_bin="$test_root/bin"
capture_dir="$test_root/capture"
test_runtime="$test_root/runtime"
mkdir -p -- "$fake_bin" "$capture_dir" "$test_runtime"
chmod 700 -- "$test_runtime"
export XDG_RUNTIME_DIR="$test_runtime"
export CLAUDE_CONFIG_DIR="$test_root/claude-config"
mkdir -m 700 -- "$CLAUDE_CONFIG_DIR"
trap 'rm -rf -- "$test_root"' EXIT

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_jq() {
  local expression="$1"
  local file="$2"
  jq -e "$expression" "$file" >/dev/null || fail "$expression"
}

assert_status() {
  local expected="$1"
  shift
  set +e
  "$@" >/dev/null 2>&1
  local actual="$?"
  set -e
  [[ "$actual" == "$expected" ]] || fail "expected status $expected, got $actual: $*"
}

cat >"$fake_bin/claude" <<'MOCK_CLAUDE'
#!/usr/bin/env bash
set -euo pipefail
jq -cn --args '$ARGS.positional' -- "$@" >"$MOCK_CAPTURE_DIR/claude-args.json"
pwd >"$MOCK_CAPTURE_DIR/claude-pwd.txt"
cat >"$MOCK_CAPTURE_DIR/claude-stdin.txt"
if [[ -n "${MOCK_EXIT:-}" ]]; then
  exit "$MOCK_EXIT"
fi
session_id=""
while (($#)); do
  case "$1" in
    --session-id|--resume)
      session_id="$2"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
jq -cn --arg session_id "$session_id" '{
  type:"result",
  subtype:"success",
  is_error:false,
  session_id:$session_id,
  modelUsage:{
    "claude-haiku-4-5-20251001":{canonicalModel:"claude-haiku-4-5"},
    "claude-opus-5":{canonicalModel:"claude-opus-5"}
  },
  structured_output:({
    verdict:"approve",
    blockers:[],
    risks:[],
    missing_verification:[],
    simpler_alternative:null,
    plan_patch:[]
  } + (if env.MOCK_SCORE == "1" then {score:90} else {} end))
}'
MOCK_CLAUDE

cat >"$fake_bin/bwrap" <<'MOCK_BWRAP'
#!/usr/bin/env bash
set -euo pipefail
jq -cn --args '$ARGS.positional' -- "$@" >"$MOCK_CAPTURE_DIR/bwrap-args.json"
claude_source=""
while (($#)); do
  if [[ "$1" == "--ro-bind" && "${3:-}" == "/usr/bin/claude" ]]; then
    claude_source="$2"
    shift 3
    continue
  fi
  if [[ "$1" == "--" ]]; then
    shift
    if [[ "${1:-}" == "/usr/bin/claude" && -n "$claude_source" ]]; then
      shift
      exec "$claude_source" "$@"
    fi
    exec "$@"
  fi
  shift
done
exit 64
MOCK_BWRAP

cat >"$fake_bin/codex" <<'MOCK_CODEX'
#!/usr/bin/env bash
set -euo pipefail
jq -cn --args '$ARGS.positional' -- "$@" >"$MOCK_CAPTURE_DIR/codex-args.json"
pwd >"$MOCK_CAPTURE_DIR/codex-pwd.txt"
cat >"$MOCK_CAPTURE_DIR/codex-stdin.txt"
if [[ -n "${MOCK_EXIT:-}" ]]; then
  exit "$MOCK_EXIT"
fi
session_id="11111111-2222-4333-8444-555555555555"
if [[ "${2:-}" == "resume" ]]; then
  for arg in "$@"; do
    if [[ "$arg" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
      session_id="$arg"
    fi
  done
fi
jq -cn --arg thread_id "$session_id" '{type:"thread.started",thread_id:$thread_id}'
if [[ "${MOCK_SCORE:-}" == "1" ]]; then
  critique='{"verdict":"approve","blockers":[],"risks":[],"missing_verification":[],"simpler_alternative":null,"plan_patch":[],"score":90}'
else
  critique='{"verdict":"approve","blockers":[],"risks":[],"missing_verification":[],"simpler_alternative":null,"plan_patch":[]}'
fi
jq -cn --arg critique "$critique" '{type:"item.completed",item:{type:"agent_message",text:$critique}}'
MOCK_CODEX

chmod +x -- "$fake_bin/claude" "$fake_bin/bwrap" "$fake_bin/codex"

packet_file="$test_root/packet.md"
printf '%s\n' '# Contract' 'Prove the adapter boundary.' >"$packet_file"
test_path="$fake_bin:/usr/bin:/bin"
export MOCK_CAPTURE_DIR="$capture_dir"

# Preserve the original one-file Claude invocation.
PATH="$test_path" "$script_dir/codex_to_claude.sh" "$packet_file" >"$test_root/claude-result.json"
assert_jq '.critic_mode == "packet" and .requested_model == "opus" and .resolved_model == "claude-opus-5" and .critic_session_id == .session_id' "$test_root/claude-result.json"
# shellcheck disable=SC2016
assert_jq '
  def next($name): . as $args | ($args | index($name)) as $index | $args[$index + 1];
  next("--model") == "opus" and
  next("--tools") == "" and
  (index("--safe-mode") != null) and
  (index("--no-chrome") != null) and
  (index("--disable-slash-commands") != null) and
  (index("--json-schema") != null) and
  (index("--system-prompt") != null) and
  (index("--add-dir") == null) and
  (index("--permission-mode") == null)
' "$capture_dir/claude-args.json"
grep -Fq 'Prove the adapter boundary.' "$capture_dir/claude-stdin.txt" || fail "Claude did not receive the packet"
grep -Fqx "$test_runtime/adversarial-plan-bounce-claude-$UID" "$capture_dir/claude-pwd.txt" || fail "Claude did not run in the neutral directory"

printf '%s\n' '# Contract' 'Accept closed stdin.' | PATH="$test_path" "$script_dir/codex_to_claude.sh" - >"$test_root/claude-stdin-result.json"
assert_jq '.structured_output.verdict == "approve"' "$test_root/claude-stdin-result.json"
grep -Fq 'Accept closed stdin.' "$capture_dir/claude-stdin.txt" || fail "Claude did not receive closed stdin"

valid_id="aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PATH="$test_path" "$script_dir/codex_to_claude_resume.sh" "$valid_id" "$packet_file" >"$test_root/claude-resume.json"
jq -e --arg expected "$valid_id" \
  '.critic_session_id == $expected and .requested_model == "opus"' \
  "$test_root/claude-resume.json" >/dev/null || fail "Claude resume session metadata is wrong"
# shellcheck disable=SC2016
assert_jq '
  def next($name): . as $args | ($args | index($name)) as $index | $args[$index + 1];
  next("--resume") == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee" and next("--model") == "opus"
' "$capture_dir/claude-args.json"
grep -Fqx "$test_runtime/adversarial-plan-bounce-claude-$UID" "$capture_dir/claude-pwd.txt" || fail "Claude resume left the neutral directory"

evidence_dir="$test_runtime/adversarial-plan-bounce-evidence.valid"
mkdir -m 700 -- "$evidence_dir"
printf '%s\n' 'ALLOWLISTED_EVIDENCE' >"$evidence_dir/evidence.txt"
chmod 600 -- "$evidence_dir/evidence.txt"

PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$evidence_dir" "$packet_file" >"$test_root/claude-evidence.json"
assert_jq '.critic_mode == "evidence" and .requested_model == "opus" and .resolved_model == "claude-opus-5"' "$test_root/claude-evidence.json"
# shellcheck disable=SC2016
assert_jq '
  def next($name): . as $args | ($args | index($name)) as $index | $args[$index + 1];
  next("--tools") == "Read,Glob,Grep" and
  (next("--system-prompt") | contains("bundle_supported")) and
  (index("--safe-mode") != null) and
  (index("--add-dir") == null)
' "$capture_dir/claude-args.json"
assert_jq '
  (index("--unshare-all") != null) and
  (index("--share-net") != null) and
  (index("--cap-drop") != null) and
  (index("--ro-bind") != null) and
  (index("--chdir") != null) and
  (index("/evidence") != null) and
  (index("/home/critic/.claude/.credentials.json") == null)
' "$capture_dir/bwrap-args.json"
grep -Fqx "$evidence_dir" "$capture_dir/claude-pwd.txt" || fail "Claude evidence mode left the bundle"

PATH="$test_path" "$script_dir/codex_to_claude_resume.sh" --evidence-dir "$evidence_dir" "$valid_id" "$packet_file" >"$test_root/claude-evidence-resume.json"
jq -e --arg expected "$valid_id" \
  '.critic_mode == "evidence" and .critic_session_id == $expected' \
  "$test_root/claude-evidence-resume.json" >/dev/null || fail "Claude evidence resume metadata is wrong"
# shellcheck disable=SC2016
assert_jq '
  def next($name): . as $args | ($args | index($name)) as $index | $args[$index + 1];
  next("--resume") == "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee" and
  next("--tools") == "Read,Glob,Grep"
' "$capture_dir/claude-args.json"
assert_jq '(index("--unshare-all") != null) and (index("/evidence") != null)' "$capture_dir/bwrap-args.json"
grep -Fqx "$evidence_dir" "$capture_dir/claude-pwd.txt" || fail "Claude evidence resume left the bundle"

critic_state_dir="$test_runtime/adversarial-plan-bounce-claude-state.$valid_id"
chmod 755 -- "$critic_state_dir"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude_resume.sh" --evidence-dir "$evidence_dir" "$valid_id" "$packet_file"
chmod 700 -- "$critic_state_dir"
rmdir -- "$critic_state_dir"
ln -s -- "$test_root" "$critic_state_dir"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude_resume.sh" --evidence-dir "$evidence_dir" "$valid_id" "$packet_file"
unlink -- "$critic_state_dir"
mkdir -m 700 -- "$critic_state_dir"

printf '%s\n' '{}' >"$CLAUDE_CONFIG_DIR/.credentials.json"
chmod 644 -- "$CLAUDE_CONFIG_DIR/.credentials.json"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$evidence_dir" "$packet_file"
unlink -- "$CLAUDE_CONFIG_DIR/.credentials.json"

assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir
outside_bundle="$test_root/adversarial-plan-bounce-evidence.outside"
mkdir -m 700 -- "$outside_bundle"
printf '%s\n' 'outside' >"$outside_bundle/evidence.txt"
chmod 600 -- "$outside_bundle/evidence.txt"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$outside_bundle" "$packet_file"

bad_name_bundle="$test_runtime/not-an-evidence-bundle"
mkdir -m 700 -- "$bad_name_bundle"
printf '%s\n' 'bad name' >"$bad_name_bundle/evidence.txt"
chmod 600 -- "$bad_name_bundle/evidence.txt"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$bad_name_bundle" "$packet_file"

symlink_bundle="$test_runtime/adversarial-plan-bounce-evidence.symlink"
mkdir -m 700 -- "$symlink_bundle"
ln -s -- "$packet_file" "$symlink_bundle/evidence.txt"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$symlink_bundle" "$packet_file"

special_bundle="$test_runtime/adversarial-plan-bounce-evidence.special"
mkdir -m 700 -- "$special_bundle"
mkfifo -m 600 -- "$special_bundle/evidence.pipe"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$special_bundle" "$packet_file"

insecure_bundle="$test_runtime/adversarial-plan-bounce-evidence.insecure"
mkdir -m 700 -- "$insecure_bundle"
printf '%s\n' 'insecure' >"$insecure_bundle/evidence.txt"
chmod 644 -- "$insecure_bundle/evidence.txt"
assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$insecure_bundle" "$packet_file"

if command -v git >/dev/null 2>&1; then
  git_bundle="$test_runtime/adversarial-plan-bounce-evidence.git"
  mkdir -m 700 -- "$git_bundle"
  git -C "$git_bundle" init -q
  printf '%s\n' 'tracked' >"$git_bundle/evidence.txt"
  chmod -R go-rwx -- "$git_bundle"
  assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude.sh" --evidence-dir "$git_bundle" "$packet_file"
fi

assert_status 64 env PATH="$test_path" "$script_dir/codex_to_claude_resume.sh" 33097 "$packet_file"
empty_packet="$test_root/empty.md"
: >"$empty_packet"
assert_status 65 env PATH="$test_path" "$script_dir/codex_to_claude.sh" "$empty_packet"
assert_status 66 env PATH="$test_path" "$script_dir/codex_to_claude.sh" "$test_root/missing.md"
python3 - "$script_dir/codex_to_claude.sh" "$test_path" "$capture_dir" <<'PY'
import errno
import os
import pty
import sys

script_path, test_path, capture_dir = sys.argv[1:]
pid, master_fd = pty.fork()
if pid == 0:
    environment = os.environ.copy()
    environment["PATH"] = test_path
    environment["MOCK_CAPTURE_DIR"] = capture_dir
    os.execve(script_path, [script_path, "-"], environment)

while True:
    try:
        if not os.read(master_fd, 4096):
            break
    except OSError as error:
        if error.errno == errno.EIO:
            break
        raise

_, wait_status = os.waitpid(pid, 0)
exit_status = os.waitstatus_to_exitcode(wait_status)
if exit_status != 64:
    raise SystemExit(f"expected TTY rejection status 64, got {exit_status}")
PY
assert_status 127 env PATH="/usr/bin:/bin" "$script_dir/codex_to_claude.sh" "$packet_file"
missing_bwrap_path="$test_root/missing-bwrap-bin"
mkdir -- "$missing_bwrap_path"
ln -s -- /usr/bin/bash "$missing_bwrap_path/bash"
ln -s -- /usr/bin/dirname "$missing_bwrap_path/dirname"
ln -s -- "$fake_bin/claude" "$missing_bwrap_path/claude"
ln -s -- /usr/bin/jq "$missing_bwrap_path/jq"
ln -s -- /usr/bin/uuidgen "$missing_bwrap_path/uuidgen"
ln -s -- /usr/bin/realpath "$missing_bwrap_path/realpath"
ln -s -- /usr/bin/find "$missing_bwrap_path/find"
ln -s -- /usr/bin/stat "$missing_bwrap_path/stat"
ln -s -- /usr/bin/install "$missing_bwrap_path/install"
ln -s -- /usr/bin/rg "$missing_bwrap_path/rg"
ln -s -- /usr/bin/git "$missing_bwrap_path/git"
ln -s -- /usr/bin/cat "$missing_bwrap_path/cat"
ln -s -- /usr/bin/tr "$missing_bwrap_path/tr"
set +e
missing_bwrap_output="$(env PATH="$missing_bwrap_path" MOCK_CAPTURE_DIR="$capture_dir" "$script_dir/codex_to_claude.sh" --evidence-dir "$evidence_dir" "$packet_file" 2>&1)"
missing_bwrap_status="$?"
set -e
[[ "$missing_bwrap_status" == 127 ]] || fail "missing bwrap returned $missing_bwrap_status"
grep -Fq 'bwrap CLI unavailable' <<<"$missing_bwrap_output" || fail "missing bwrap was not diagnosed"
assert_status 42 env PATH="$test_path" MOCK_CAPTURE_DIR="$capture_dir" MOCK_EXIT=42 "$script_dir/codex_to_claude.sh" "$packet_file"
assert_status 65 env PATH="$test_path" MOCK_CAPTURE_DIR="$capture_dir" MOCK_SCORE=1 "$script_dir/codex_to_claude.sh" "$packet_file"

# Preserve the original one-file Codex invocation.
PATH="$test_path" "$script_dir/claude_to_codex.sh" "$packet_file" >"$test_root/codex-result.jsonl"
head -n 1 "$test_root/codex-result.jsonl" >"$test_root/codex-metadata.json"
assert_jq '.type == "critic_session" and .critic == "codex" and .critic_session_id == "11111111-2222-4333-8444-555555555555"' "$test_root/codex-metadata.json"
assert_jq '
  (index("exec") != null) and
  (index("-C") != null) and
  (index("--sandbox") != null) and
  (index("read-only") != null) and
  (index("--ignore-user-config") != null) and
  (index("--ignore-rules") != null) and
  (index("--output-schema") != null) and
  (index("--json") != null) and
  (index("--ephemeral") == null)
' "$capture_dir/codex-args.json"
grep -Eq '/adversarial-plan-bounce-codex-[0-9]+$' "$capture_dir/codex-pwd.txt" || fail "Codex did not run in the neutral directory"

printf '%s\n' '# Contract' 'Accept Codex stdin.' | PATH="$test_path" "$script_dir/claude_to_codex.sh" - >"$test_root/codex-stdin.jsonl"
grep -Fq 'Accept Codex stdin.' "$capture_dir/codex-stdin.txt" || fail "Codex did not receive closed stdin"

PATH="$test_path" "$script_dir/claude_to_codex_resume.sh" "$valid_id" "$packet_file" >"$test_root/codex-resume.jsonl"
head -n 1 "$test_root/codex-resume.jsonl" >"$test_root/codex-resume-metadata.json"
jq -e --arg expected "$valid_id" \
  '.critic_session_id == $expected' \
  "$test_root/codex-resume-metadata.json" >/dev/null || fail "Codex resume session metadata is wrong"
assert_jq '(index("exec") != null) and (index("resume") != null) and (index("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee") != null)' "$capture_dir/codex-args.json"
grep -Eq '/adversarial-plan-bounce-codex-[0-9]+$' "$capture_dir/codex-pwd.txt" || fail "Codex resume left the neutral directory"

assert_status 64 env PATH="$test_path" "$script_dir/claude_to_codex_resume.sh" 33097 "$packet_file"
assert_status 127 env PATH="/usr/bin:/bin" "$script_dir/claude_to_codex.sh" "$packet_file"
assert_status 42 env PATH="$test_path" MOCK_CAPTURE_DIR="$capture_dir" MOCK_EXIT=42 "$script_dir/claude_to_codex.sh" "$packet_file"
assert_status 65 env PATH="$test_path" MOCK_CAPTURE_DIR="$capture_dir" MOCK_SCORE=1 "$script_dir/claude_to_codex.sh" "$packet_file"

jq -e . "$skill_dir/scripts/critique.schema.json" >/dev/null
printf '%s\n' 'adapter tests passed'

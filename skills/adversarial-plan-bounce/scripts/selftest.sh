#!/usr/bin/env bash
# Deterministic self-heal tests for bounce_codex.py against FAKE codex stand-ins (no real Codex call).
#   T1 repair + verdict-band correction: malformed JSON then valid JSON with a wrong verdict.
#   T2 model rotation: the first model hits a model-level failure -> driver rotates to the next fallback.
#   T3 no rotation on a generic failure: a plain empty-output / non-model error stays a hard error.
# Exit 0 only if all three behave as specified.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
skill_dir="$(dirname "$here")"
driver="$skill_dir/scripts/bounce_codex.py"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/s1" "$tmp/s2" "$tmp/s3"
printf '# fake plan\n\nA throwaway plan for the self-heal test.\n' > "$tmp/plan.md"

VALID_JSON='{"score":88,"verdict":"agreed","summary":"fake review","structural_blockers":[],"findings":[],"held_decisions":[],"execution_mode_clear":true,"resolved_prior_blockers":[],"remaining_prior_blockers":[]}'

# --- helper: extract the -o output path and the -m model from a fake-codex argv ---------------------
read -r -d '' ARGPARSE <<'ARG' || true
out=""; model=""; prev=""
for arg in "$@"; do
  [ "$prev" = "-o" ] && out="$arg"
  [ "$prev" = "-m" ] && model="$arg"
  prev="$arg"
done
cat >/dev/null  # drain the prompt on stdin
ARG

# ========================= T1: repair + verdict-band correction ====================================
cat > "$tmp/fake-codex-1" <<FAKE
#!/usr/bin/env bash
$ARGPARSE
count_file="\$FAKE_STATE/count"
n=0; [ -f "\$count_file" ] && n="\$(cat "\$count_file")"; n=\$((n + 1)); echo "\$n" > "\$count_file"
if [ "\$n" -eq 1 ]; then
  printf '{ this is not valid json' > "\$out"   # -> repair path
else
  printf '%s' '$VALID_JSON' > "\$out"            # valid, wrong verdict -> verdict self-correction
fi
exit 0
FAKE
chmod +x "$tmp/fake-codex-1"

FAKE_STATE="$tmp/s1" uv run --with jsonschema python "$driver" \
  --plan "$tmp/plan.md" --repo "$tmp" --iteration 1 --workspace "$tmp/ws1" \
  --codex-bin "$tmp/fake-codex-1" --target-score 95 --max-attempts 3 --timeout-seconds 60
iter1="$tmp/ws1/iteration-001"
echo "--- T1 self-heal.log ---"; cat "$iter1/self-heal.log"
grep -q "failed (repair)" "$iter1/self-heal.log" || { echo "FAIL T1: repair path not exercised"; exit 1; }
grep -q "corrected verdict" "$iter1/self-heal.log" || { echo "FAIL T1: verdict correction not exercised"; exit 1; }
python3 - "$iter1/score.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
assert d["verdict"] == "blockers-remain", d
assert d["done"] is False, d
PY
echo "T1 OK: repair + verdict-correction fired, score.json consistent"

# ========================= T2: model rotation on a model-level failure =============================
# The fake fails (model-not-found) for whatever model it sees FIRST, and succeeds on any other model,
# so the test is independent of the machine's configured primary model.
cat > "$tmp/fake-codex-2" <<FAKE
#!/usr/bin/env bash
$ARGPARSE
first_file="\$FAKE_STATE/firstmodel"
[ -f "\$first_file" ] || echo "\$model" > "\$first_file"
first="\$(cat "\$first_file")"
if [ "\$model" = "\$first" ]; then
  echo '404 Not Found: unknown model: "'"\$model"'"' >&2   # model-level signature -> rotate
  exit 1
fi
printf '%s' '$VALID_JSON' > "\$out"                          # a fallback model succeeds
exit 0
FAKE
chmod +x "$tmp/fake-codex-2"

FAKE_STATE="$tmp/s2" uv run --with jsonschema python "$driver" \
  --plan "$tmp/plan.md" --repo "$tmp" --iteration 1 --workspace "$tmp/ws2" \
  --codex-bin "$tmp/fake-codex-2" --target-score 95 --max-attempts 1 --timeout-seconds 60
iter2="$tmp/ws2/iteration-001"
echo "--- T2 self-heal.log ---"; cat "$iter2/self-heal.log"
grep -q "model rotation: .* hit a model-level failure; trying" "$iter2/self-heal.log" \
  || { echo "FAIL T2: did not rotate on a model-level failure"; exit 1; }
grep -q "recovered on fallback model" "$iter2/self-heal.log" \
  || { echo "FAIL T2: did not recover on a fallback model"; exit 1; }
echo "T2 OK: rotated off the failing model and recovered on a fallback"

# ========================= T3: NO rotation on a generic empty-output failure =======================
cat > "$tmp/fake-codex-3" <<FAKE
#!/usr/bin/env bash
$ARGPARSE
echo 'connection reset by peer' >&2   # NOT a model signature -> must stay a hard error, no rotation
exit 1
FAKE
chmod +x "$tmp/fake-codex-3"

if FAKE_STATE="$tmp/s3" uv run --with jsonschema python "$driver" \
  --plan "$tmp/plan.md" --repo "$tmp" --iteration 1 --workspace "$tmp/ws3" \
  --codex-bin "$tmp/fake-codex-3" --target-score 95 --max-attempts 1 --timeout-seconds 60 2>/dev/null
then
  echo "FAIL T3: expected a hard non-zero exit on a generic failure"; exit 1
fi
iter3="$tmp/ws3/iteration-001"
echo "--- T3 self-heal.log ---"; cat "$iter3/self-heal.log"
if grep -q "model rotation" "$iter3/self-heal.log"; then
  echo "FAIL T3: rotated models on a non-model failure (would mask prompt/runtime/API errors)"; exit 1
fi
echo "T3 OK: a generic empty-output failure stayed a hard error, no model churn"

echo "selftest OK: T1 repair+verdict, T2 model-rotation, T3 no-rotation-on-generic all passed"

"""Runtime touch-set boundary check for slice-conductor (the cwd-bleed / scope guard).

Asserts everything a slice changed in its worktree (committed since base_sha + untracked files) is
COVERED by its declared touch_set, using the SAME matcher as the gate (`paths_overlap` from
to-slices/validate_dag.py) so the gate and runtime check can't drift on glob semantics. It loads the
SAME project-config as the gate (via --config or HARNESS_PROJECT_CONFIG) so `package_prefix`
normalization matches. The only allowed source of `boundary_ok`; the conductor runs it after every
implementer turn and before any merge. Emits machine JSON; exit 1 on any out-of-scope path.

Run: uv run --with jsonschema python <slice-conductor>/scripts/boundary_check.py \
       <slices.json> <slice_id> <worktree_path> <base_sha> [--config <project-config.json>]
(--with jsonschema is needed because importing validate_dag pulls it in.)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Reuse the gate's matcher + config loader — single source of truth for path overlap + taxonomy.
_VD_DIR = Path(__file__).resolve().parents[2] / "to-slices" / "scripts"
sys.path.insert(0, str(_VD_DIR))
from validate_dag import load_project_config, paths_overlap  # noqa: E402


def _git(worktree: str, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", worktree, *args], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main(slices_path: str, slice_id: str, worktree: str, base_sha: str, cfg_path: str | None) -> int:
    load_project_config(cfg_path)  # match the gate's package_prefix / taxonomy
    doc = json.loads(Path(slices_path).read_text())
    slc = next((s for s in doc["slices"] if str(s["id"]) == slice_id), None)
    if slc is None:
        print(json.dumps({"boundary_ok": False, "error": f"slice {slice_id} not in {slices_path}"}))
        return 1
    touch_set = [str(p) for p in slc["touch_set"]]
    committed = _git(worktree, "diff", "--name-only", f"{base_sha}...HEAD")
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard")
    changed = sorted(set(committed) | set(untracked))
    # a concrete changed path is in scope if ANY touch_set entry covers it (glob/dir-aware)
    out_of_scope = [p for p in changed if not any(paths_overlap(p, e) for e in touch_set)]
    ok = not out_of_scope
    print(json.dumps({
        "boundary_ok": ok,
        "slice_id": slice_id,
        "base_sha": base_sha,
        "changed": changed,
        "out_of_scope": out_of_scope,
        "touch_set": touch_set,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    cfg_path: str | None = None
    if "--config" in argv:
        ci = argv.index("--config")
        cfg_path = argv[ci + 1]
        argv = argv[:ci] + argv[ci + 2:]
    if len(argv) != 4:
        raise SystemExit(
            "usage: boundary_check.py <slices.json> <slice_id> <worktree_path> <base_sha> "
            "[--config <project-config.json>]")
    raise SystemExit(main(argv[0], argv[1], argv[2], argv[3], cfg_path))

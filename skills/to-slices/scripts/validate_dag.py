"""Validate a slices.json DAG for the slice-conductor orchestration loop.

Fail-loud gate run by `to-slices` (and re-run by `slice-conductor` before it dispatches anything).
Each check is a hard stop — a malformed decomposition is caught BEFORE any agent spawns, with the
offending pair/cycle/edge printed so it can be re-cut.

Checks:
  1. schema      — conforms to orchestration/contracts/slices.schema.json
  2. well-formed — slice ids unique, blocked_by ids exist, no self-edge
  3. mode        — (per --mode) dry-run needs approved=false + null ids; publish/dispatch need
                   approved=true; dispatch also needs a published DAG (non-null ids)
  4. acyclic     — Kahn's algorithm; prints a concrete cycle path on failure
  5. collision   — concurrently-runnable pairs (a DAG antichain) must NOT collide: collide =
                   touch_sets share a path (glob + directory matching, not exact string) OR both
                   slices are shared-core (foundational files run serially)

`shared_core` is DERIVED from touch_set, not trusted from the flag. layer_rank is advisory only.

PROJECT CONFIG (the host project's taxonomy): `shared_core`, the layer map, and the `package_prefix`
are NOT hardcoded — they come from a project-config (orchestration/project-config.schema.json) supplied
via `--config <path>` or the HARNESS_PROJECT_CONFIG env var. WITHOUT a config the structural checks
(schema, well-formedness, acyclicity, touch_set-overlap collisions) still run at full strength; only
shared-core serialization and advisory layer ranks are disabled, with a loud warning. See
orchestration/sample-project-config.json.

Run: uv run --with jsonschema python <this validate_dag.py> <slices.json>
     [--mode structural|dry-run|publish|dispatch] [--config <project-config.json>]
Exit 0 = valid; exit 1 = a check failed (reason on stderr). The same path-overlap matcher
(`paths_overlap`) is what slice-conductor's runtime boundary check imports — keep them in sync; both
call `load_project_config` so the gate and the runtime scope check see the same taxonomy.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

# Project taxonomy — EMPTY until load_project_config() populates it from the host project's config.
# Empty = zero-config mode: structural checks run fully; shared-core serialization + layer ranks off.
SHARED_CORE: tuple[str, ...] = ()
# path-prefix -> advisory layer rank (display only; NOT a hard gate — vertical slices span layers).
_LAYERS: tuple[tuple[str, int], ...] = ()
# A path prefix stripped from touch_set entries and `git diff --name-only` output before comparison.
_PKG_PREFIX = ""
_GLOB = "*?["


def _find_repo(start: Path) -> Path:
    rel = "orchestration/contracts/slices.schema.json"
    for parent in [start, *start.parents]:
        if (parent / rel).is_file():
            return parent
    raise SystemExit(f"FATAL: could not locate {rel} above {start}")


REPO = _find_repo(Path(__file__).resolve())
SCHEMA_PATH = REPO / "orchestration/contracts/slices.schema.json"
CONFIG_SCHEMA_PATH = REPO / "orchestration/project-config.schema.json"


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_project_config(cfg_path: str | None) -> dict[str, object]:
    """Resolve + load the host project's taxonomy, setting the module globals SHARED_CORE,
    _LAYERS, _PKG_PREFIX. Resolution order: explicit --config path -> HARNESS_PROJECT_CONFIG env
    -> none (zero-config mode + loud warning). Returns the config dict ({} in zero-config mode).
    boundary_check.py imports and calls this so the runtime scope check uses the same taxonomy."""
    global SHARED_CORE, _LAYERS, _PKG_PREFIX
    path = cfg_path or os.environ.get("HARNESS_PROJECT_CONFIG") or None
    if path is None:
        print("WARN  no project-config (--config / HARNESS_PROJECT_CONFIG): shared-core "
              "serialization + layer ranks DISABLED. Structural checks still run at full strength. "
              "Supply orchestration/sample-project-config.json to enable them.", file=sys.stderr)
        SHARED_CORE, _LAYERS, _PKG_PREFIX = (), (), ""
        return {}
    cfg: dict[str, object] = json.loads(Path(path).read_text())
    schema = json.loads(CONFIG_SCHEMA_PATH.read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(cfg), key=lambda e: list(e.path))
    if errors:
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"      project-config: {loc}: {err.message}", file=sys.stderr)
        _fail(f"{path} does not conform to project-config.schema.json")
    SHARED_CORE = tuple(cfg.get("shared_core", []))  # type: ignore[arg-type]
    layers: list[list[str]] = cfg.get("layers", [])  # type: ignore[assignment]
    _LAYERS = tuple((prefix, rank) for rank, group in enumerate(layers) for prefix in group)
    _PKG_PREFIX = str(cfg.get("package_prefix", ""))
    return cfg


def _norm(p: str) -> str:
    p = p.strip().rstrip("/")
    return p[len(_PKG_PREFIX):] if _PKG_PREFIX and p.startswith(_PKG_PREFIX) else p


def _dir_prefix(d: str, p: str) -> bool:
    return p == d or p.startswith(d + "/")


def _literal_dir(p: str) -> str:
    """Literal directory prefix of a glob entry — everything before its first glob char, to the last
    `/`. E.g. `tests/*.py`->`tests`; `adapters/primary/*`->`adapters/primary`; `*.py`->``."""
    idx = min((p.find(c) for c in _GLOB if c in p), default=len(p))
    head = p[:idx]
    return head.rsplit("/", 1)[0] if "/" in head else ""


def paths_overlap(a: str, b: str) -> bool:
    """True if two touch_set entries can refer to a common path.

    Handles exact equality, directory containment (`core/` covers `core/table.ts`), glob-vs-literal
    (`tests/**` covers `tests/test_x.ts`), and glob-vs-glob (`tests/*.ts` and `tests/test_*` both
    match `tests/test_x.ts`). CONSERVATIVE: any plausible overlap is a collision (two globs whose
    literal dirs nest can share a file). boundary_check.py reuses this matcher so the gate and the
    runtime scope check can't drift on glob semantics.
    """
    a, b = _norm(a), _norm(b)
    if a == b:
        return True
    a_glob = any(c in a for c in _GLOB)
    b_glob = any(c in b for c in _GLOB)
    if a_glob and fnmatch.fnmatch(b, a):
        return True
    if b_glob and fnmatch.fnmatch(a, b):
        return True
    if a_glob and b_glob:
        da, db = _literal_dir(a), _literal_dir(b)
        # two globs collide unless their literal directories are in disjoint subtrees
        if da == "" or db == "" or _dir_prefix(da, db) or _dir_prefix(db, da):
            return True
    return _dir_prefix(a, b) or _dir_prefix(b, a)


def _touch_overlap(ts_a: list[str], ts_b: list[str]) -> list[str]:
    hits = {f"{a} ~ {b}" for a in ts_a for b in ts_b if paths_overlap(a, b)}
    return sorted(hits)


def is_shared_core(touch_set: list[str]) -> bool:
    return any(paths_overlap(p, core) for p in touch_set for core in SHARED_CORE)


def max_layer_rank(touch_set: list[str]) -> int:
    ranks = [
        rank for p in touch_set for prefix, rank in _LAYERS
        if _dir_prefix(_norm(prefix), _norm(p)) or _norm(p) == _norm(prefix)
    ]
    return max(ranks, default=0)


def _ancestors(deps: dict[str, list[str]]) -> dict[str, set[str]]:
    memo: dict[str, set[str]] = {}

    def visit(node: str) -> set[str]:
        if node in memo:
            return memo[node]
        memo[node] = set()
        acc: set[str] = set()
        for dep in deps[node]:
            acc.add(dep)
            acc |= visit(dep)
        memo[node] = acc
        return acc

    for node in deps:
        visit(node)
    return memo


def _find_cycle(deps: dict[str, list[str]]) -> list[str]:
    white, gray, black = 0, 1, 2
    color = dict.fromkeys(deps, white)
    stack: list[str] = []

    def dfs(node: str) -> list[str]:
        color[node] = gray
        stack.append(node)
        for dep in deps[node]:
            if color[dep] == gray:
                return stack[stack.index(dep):] + [dep]
            if color[dep] == white:
                found = dfs(dep)
                if found:
                    return found
        color[node] = black
        stack.pop()
        return []

    for node in deps:
        if color[node] == white:
            found = dfs(node)
            if found:
                return found
    return ["<cycle>"]


def _schema_check(doc: dict[str, object]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.path))
    if errors:
        for err in errors:
            loc = "/".join(str(p) for p in err.path) or "<root>"
            print(f"      schema: {loc}: {err.message}", file=sys.stderr)
        _fail("slices.json does not conform to slices.schema.json")


def _mode_check(doc: dict[str, object], slices: list[dict[str, object]], mode: str) -> None:
    campaign: dict[str, object] = doc["campaign"]  # type: ignore[assignment]
    approved = bool(campaign["approved"])
    parent = campaign.get("linear_parent_id")
    ids_null = parent is None and all(s.get("linear_issue_id") is None for s in slices)
    ids_full = parent is not None and all(s.get("linear_issue_id") is not None for s in slices)
    if mode == "dry-run":
        if approved:
            _fail("dry-run artifact must have campaign.approved=false")
        if not ids_null:
            _fail("dry-run artifact must have null linear_parent_id and every linear_issue_id=null")
    elif mode in ("publish", "dispatch"):
        if not approved:
            _fail(f"{mode} mode requires campaign.approved=true (user has not approved this DAG)")
        if mode == "dispatch" and not ids_full:
            _fail("dispatch requires a PUBLISHED DAG: non-null linear_parent_id and every "
                  "linear_issue_id")


def main(path: str, mode: str, cfg_path: str | None) -> int:
    load_project_config(cfg_path)
    doc: object = json.loads(Path(path).read_text())
    if not isinstance(doc, dict):
        _fail("slices.json is not a JSON object")
    assert isinstance(doc, dict)
    _schema_check(doc)

    slices: list[dict[str, object]] = doc["slices"]  # type: ignore[assignment]
    ids = [str(s["id"]) for s in slices]
    by_id: dict[str, dict[str, object]] = {str(s["id"]): s for s in slices}
    if len(set(ids)) != len(ids):
        _fail("duplicate slice ids")

    _mode_check(doc, slices, mode)

    deps: dict[str, list[str]] = {i: [str(b) for b in by_id[i]["blocked_by"]] for i in ids}  # type: ignore[union-attr]
    touch: dict[str, list[str]] = {i: [str(p) for p in by_id[i]["touch_set"]] for i in ids}  # type: ignore[union-attr]
    shared: dict[str, bool] = {i: is_shared_core(touch[i]) for i in ids}

    # 2. well-formed edges + shared_core flag honesty
    for sid, blockers in deps.items():
        for b in blockers:
            if b == sid:
                _fail(f"slice {sid} is blocked_by itself")
            if b not in by_id:
                _fail(f"slice {sid} blocked_by unknown slice {b!r}")
        declared = bool(by_id[sid].get("shared_core", False))
        if declared != shared[sid]:
            verb = "touches a shared-core file but shared_core is not set true" if shared[sid] \
                else "sets shared_core=true but touches no shared-core file"
            _fail(f"slice {sid} {verb} (touch_set={touch[sid]}); fix the flag or re-cut")

    # 4. acyclicity — Kahn's algorithm
    indeg = {i: len(deps[i]) for i in ids}
    succ: dict[str, list[str]] = {i: [] for i in ids}
    for i in ids:
        for d in deps[i]:
            succ[d].append(i)
    queue = [i for i in ids if indeg[i] == 0]
    drained = 0
    while queue:
        node = queue.pop()
        drained += 1
        for nxt in succ[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    if drained != len(ids):
        _fail("blocked_by graph has a cycle: " + " -> ".join(_find_cycle(deps)))

    # 5. collision — concurrently-runnable (antichain) slices must not collide
    anc = _ancestors(deps)
    for a_i in range(len(ids)):
        for b_i in range(a_i + 1, len(ids)):
            u, v = ids[a_i], ids[b_i]
            if v in anc[u] or u in anc[v]:
                continue  # one depends on the other → never concurrent
            overlap = _touch_overlap(touch[u], touch[v])
            if overlap:
                _fail(f"collision: {u} and {v} can run concurrently but their touch_sets overlap "
                      f"({overlap}) — add a blocked_by edge (serialize) or re-cut")
            if shared[u] and shared[v]:
                _fail(f"collision: {u} and {v} are both shared-core (foundational files run "
                      f"serially) but can run concurrently — add a blocked_by edge to order them")

    ceiling = doc["campaign"].get("concurrency_ceiling", 5)  # type: ignore[union-attr]
    layer_ranks = {i: max_layer_rank(touch[i]) for i in ids}  # advisory, display only
    print(f"OK  {len(slices)} slices form a collision-free acyclic DAG "
          f"(mode={mode}, ceiling={ceiling}, shared_core={sorted(i for i in ids if shared[i])}, "
          f"layer_ranks={layer_ranks}).")
    return 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    mode = "structural"
    cfg_path: str | None = None
    if "--mode" in argv:
        mi = argv.index("--mode")
        mode = argv[mi + 1]
        argv = argv[:mi] + argv[mi + 2:]
    if "--config" in argv:
        ci = argv.index("--config")
        cfg_path = argv[ci + 1]
        argv = argv[:ci] + argv[ci + 2:]
    if len(argv) != 1 or mode not in ("structural", "dry-run", "publish", "dispatch"):
        raise SystemExit(
            "usage: validate_dag.py <slices.json> [--mode structural|dry-run|publish|dispatch] "
            "[--config <project-config.json>]")
    raise SystemExit(main(argv[0], mode, cfg_path))

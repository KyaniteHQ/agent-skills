# Metric commands (tested, production-only)

All commands run from the repo root and ephemerally via `uvx` — they never touch
`pyproject.toml` or `uv.lock`. Run them only over PRODUCTION code; `tests/**`,
`scripts/**`, and any non-production directories are excluded by listing the prod
paths explicitly.

## (A) Cyclomatic complexity — radon

```
uvx radon cc -s -j -n C <prod_package_1> <prod_package_2> <flat_module.py> ...
```

- `-s` score, `-j` JSON, `-n C` rank C and above (CC >= 10).
- JSON shape: `{ "<file>": [ {name, lineno, endline, complexity, rank, type,
  classname, closures} ] }`. Rank E/D/C are the hotspots; `closures` are nested
  functions with their own CC.
- Drop `-n C` to see every function (rank A+). Never scan `tests`/`scripts` or
  any non-production directories.
- Replace `<prod_package_1> ...` with the actual package/module names for the
  target project (supplied in campaign config under {{SCOPE}}).

**Example output shape (generic placeholders):**

```
Current prod hotspots: module_a::entry_point CC=38/E,
pkg.core::_process_job 20/C, pkg.adapters::Adapter.solve 18/C.
```

## (B) Import-graph community detection — grimp + networkx Louvain

```
uvx --with grimp --with networkx python -c "
import sys; sys.path.insert(0, '.')   # REQUIRED first line — flat uninstalled layout
import grimp, networkx as nx
from networkx.algorithms.community import louvain_communities
PKGS = ('pkg_a', 'pkg_b', 'pkg_c')   # replace with project's top-level packages
g = grimp.build_graph(*PKGS)
G = nx.DiGraph(); G.add_nodes_from(g.modules)
for m in g.modules:
    for dep in g.find_modules_that_directly_import(m):
        G.add_edge(dep, m)
comms = louvain_communities(G.to_undirected(), seed=42)
for i, c in enumerate(comms): print(f'C{i}:', sorted(c))
print('communities:', len(comms), 'modules:', len(g.modules))
"
```

- `sys.path.insert(0, '.')` MUST be first or grimp raises `NotATopLevelModule`.
- Flat-module files (`worker.py`, `config.py`, `models.py`) are not package nodes —
  grimp sees packages only. That is fine; flat orchestrator modules are not domain
  packages to community-check.
- `seed=42` keeps the partition deterministic across runs.
- Replace `PKGS` with the actual top-level packages for the target project.

### Reading the output — a cross-package community is a HINT, not a verdict

A community spanning >= 2 top-level packages, or a package split across >= 2
communities, is a *suspect* only. To act, write a falsifiable **boundary claim**:

> "`module_a` imports `module_b` for reason `X`, which belongs behind port `Y` /
> on layer `Z`."

No boundary claim -> drop the candidate.

**Exempt:** the project's composition root (if one exists). A composition root
wiring all adapters together will appear in a community with every adapter it
wires — that is by design, not a leak.

**Example suspect (generic):** a community that clusters an event-emitter module
with unrelated infrastructure packages may indicate a same-transaction store
coupling worth investigating before proposing any move.

"""Regression guard for the config-driven path taxonomy in validate_dag.

The host project supplies `package_prefix` (a path prefix git emits but touch_sets omit), `shared_core`
(files that serialize), and `layers` (advisory ranks) via a project-config. `_norm` strips the prefix
on both sides so the gate's shared-core/collision logic and the runtime boundary check
(boundary_check.py, which imports paths_overlap + load_project_config) agree on one path space.

This test loads orchestration/sample-project-config.json and asserts the taxonomy behaves.

Run: uv run --with jsonschema python <path>/test_validate_dag_paths.py
"""

from __future__ import annotations

from validate_dag import (
    REPO,
    is_shared_core,
    load_project_config,
    max_layer_rank,
    paths_overlap,
)


def main() -> int:
    load_project_config(str(REPO / "orchestration/sample-project-config.json"))

    # A prefixed git path and a package-relative touch entry must overlap (both ways).
    assert paths_overlap("src/service.ts", "service.ts")
    assert paths_overlap("service.ts", "src/service.ts")
    assert paths_overlap("src/app/main.ts", "app/main.ts")

    # Shared-core detection must fire through the prefix (sample shared_core lists these).
    assert is_shared_core(["src/interfaces.ts"])
    assert is_shared_core(["src/config.ts"])
    assert is_shared_core(["src/core/table.ts"])  # core/ is a shared-core dir
    assert max_layer_rank(["src/service.ts"]) == 5  # service.ts is layer index 5 in the sample

    # Distinct files in the same package dir must NOT collide (the gate's core guarantee).
    assert not paths_overlap("src/service.ts", "src/interfaces.ts")
    assert not paths_overlap("tests/a.test.ts", "tests/b.test.ts")
    assert paths_overlap("tests/x.test.ts", "tests/x.test.ts")

    # Directory containment works regardless of config.
    assert paths_overlap("core/", "core/engine.ts")

    # Zero-config mode: shared-core detection is disabled (empty taxonomy), structural matching stays.
    load_project_config(None)
    assert not is_shared_core(["interfaces.ts"])  # no config -> nothing is shared-core
    assert paths_overlap("core/", "core/engine.ts")  # dir containment is config-independent

    print("OK  config-driven taxonomy: prefix normalization + shared_core + layers + zero-config")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

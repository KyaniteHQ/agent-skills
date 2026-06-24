"""Compute the launch set for slice-conductor from slices.json + the run ledger.

The conductor calls this each scheduling tick to decide which slices to spawn next WITHOUT
hand-tracking the DAG. Eligibility = every blocked_by slice is `merged`; the launch set is the
eligible slices capped by the remaining concurrency slots (ceiling - in-flight). This assumes an
already-VALID DAG — run to-slices' validate_dag.py first.

`merged` here means **merged into the integration branch** (loop.md §5a), not on `main` — that is
what satisfies a dependent's blocked_by. `complete` (every slice merged into integration) is the
signal for the conductor to run the SINGLE integration->main babysit-pr ship (loop.md §5b).

CEILING SEMANTICS — the ceiling bounds in-flight SLICES, which equals the count of PERSISTENT
implementers (one live `impl-<id>` per in-flight slice). Reviewers do NOT count against it: a
`rev-<id>` is spawned for a single verdict pass and torn down right after the conductor reads it
(loop.md section 2), so reviewers never accumulate. Live teammate count therefore stays ≈
`in_flight` implementers plus the few slices momentarily in a review window — NOT 2x the ceiling.
The agent-teams docs' 3-5 guidance is about the persistent set; `persistent_teammates` in the
output is that number, so the reconciliation is visible at every tick.

Run: uv run python <slice-conductor>/scripts/frontier.py <slices.json> [<ledger.json>]
Prints a JSON object: {complete, stuck, ceiling, merged, in_flight, persistent_teammates, eligible,
launch, held, blocked, remaining}. `stuck=true` means nothing is running and nothing is eligible but
the run is not complete — held/blocked slices are gating progress and need the owner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_MERGED = "merged"
_IN_FLIGHT = frozenset({"dispatched", "changes", "pass", "shipped"})


def main(slices_path: str, ledger_path: str | None) -> int:
    doc = json.loads(Path(slices_path).read_text())
    slices: list[dict[str, object]] = doc["slices"]
    ids = [str(s["id"]) for s in slices]
    deps: dict[str, list[str]] = {str(s["id"]): [str(b) for b in s["blocked_by"]] for s in slices}  # type: ignore[union-attr]
    ceiling = int(doc["campaign"].get("concurrency_ceiling", 5))  # type: ignore[union-attr]

    phase: dict[str, str] = dict.fromkeys(ids, "pending")
    if ledger_path and Path(ledger_path).is_file():
        ledger = json.loads(Path(ledger_path).read_text())
        for rec in ledger.get("slices", []):
            sid = str(rec.get("slice_id"))
            if sid in phase:
                phase[sid] = str(rec.get("phase", "pending"))

    merged = [i for i in ids if phase[i] == _MERGED]
    in_flight = [i for i in ids if phase[i] in _IN_FLIGHT]
    held = [i for i in ids if phase[i] == "held"]
    blocked = [i for i in ids if phase[i] == "blocked"]

    eligible = [
        i for i in ids
        if phase[i] == "pending" and all(phase[b] == _MERGED for b in deps[i])
    ]
    slots = max(0, ceiling - len(in_flight))
    launch = eligible[:slots]

    complete = len(merged) == len(ids)
    stuck = (not complete) and (not in_flight) and (not eligible)

    print(json.dumps({
        "complete": complete,
        "stuck": stuck,
        "ceiling": ceiling,
        "merged": merged,
        "in_flight": in_flight,
        "persistent_teammates": len(in_flight),
        "eligible": eligible,
        "launch": launch,
        "held": held,
        "blocked": blocked,
        "remaining": [i for i in ids if phase[i] != _MERGED],
    }, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit("usage: frontier.py <slices.json> [<ledger.json>]")
    raise SystemExit(main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None))

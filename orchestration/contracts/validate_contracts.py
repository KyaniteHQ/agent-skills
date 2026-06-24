"""Validate each orchestration contract fixture against its JSON Schema. Fail loud.

Run: uv run --with jsonschema python orchestration/contracts/validate_contracts.py

This is build-step 1's gate: it proves the 5 contracts (slices DAG, implementer report,
reviewer report, ledger entry, Linear write) are internally consistent before the to-slices
and slice-conductor skills are written against them. Exits non-zero on any failure.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

CONTRACTS = Path(__file__).parent
PAIRS: tuple[tuple[str, str], ...] = (
    ("slices.schema.json", "fixtures/slices.example.json"),
    ("implementer-report.schema.json", "fixtures/implementer-report.example.json"),
    ("reviewer-report.schema.json", "fixtures/reviewer-report.example.json"),
    ("ledger-entry.schema.json", "fixtures/ledger-entry.example.json"),
    ("run-ledger.schema.json", "fixtures/run-ledger.example.json"),
    ("linear-write.schema.json", "fixtures/linear-write.example.json"),
)


def _load(rel: str) -> dict[str, object]:
    data: object = json.loads((CONTRACTS / rel).read_text())
    if not isinstance(data, dict):
        raise TypeError(f"{rel} is not a JSON object")
    return data


def main() -> int:
    failures = 0
    for schema_rel, fixture_rel in PAIRS:
        schema = _load(schema_rel)
        Draft202012Validator.check_schema(schema)  # the schema itself must be well-formed
        validator = Draft202012Validator(schema)
        fixture = _load(fixture_rel)
        errors = sorted(validator.iter_errors(fixture), key=lambda e: list(e.path))
        if errors:
            failures += 1
            print(f"FAIL  {fixture_rel}  vs  {schema_rel}")
            for err in errors:
                loc = "/".join(str(p) for p in err.path) or "<root>"
                print(f"      - {loc}: {err.message}")
        else:
            print(f"PASS  {fixture_rel}  vs  {schema_rel}")
    if failures:
        print(f"\n{failures} contract(s) failed validation.", file=sys.stderr)
        return 1
    print(f"\nAll {len(PAIRS)} contracts valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

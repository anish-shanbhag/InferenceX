#!/usr/bin/env python3
"""Collect legacy rows while retaining versioned validation provenance."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from infx.results.contracts import digest_file, digest_json, utc_now  # noqa: E402


def collect(roots: list[Path], schema_dir: Path) -> tuple[list[Any], dict, dict]:
    legacy: list[Any] = []
    records: list[dict] = []
    inputs: list[dict] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            item = {"path": f"{root.name}/{path.relative_to(root)}", "digest": digest_file(path),
                    "kind": "unknown", "status": "unreadable", "errors": []}
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                item["errors"] = [f"{type(exc).__name__}: {exc}"]
                inputs.append(item)
                continue
            dtype = value.get("document_type") if isinstance(value, dict) else None
            if isinstance(dtype, str) and dtype.startswith("inferencex."):
                item["kind"] = dtype
                try:
                    from infx.results.contract_models import validate_exchange_document

                    validate_exchange_document(value, schema_dir)
                except Exception as exc:  # retain validation evidence, keep collecting
                    item["status"] = "invalid"
                    item["errors"] = [str(exc)]
                else:
                    item["status"] = "valid"
                    if dtype == "inferencex.result-record":
                        records.append(value["result"])
                inputs.append(item)
                continue
            item.update(kind="legacy-result", status="legacy")
            legacy.append(value)
            inputs.append(item)
    now = utc_now()
    snapshot = digest_json([{"path": x["path"], "digest": x["digest"]} for x in inputs])
    result_set = {
        "document_type": "inferencex.result-set", "schema_version": "inferencex.exchange/v1",
        "generated_at": now,
        "source": {"service": "inferencex-actions-collector", "snapshot_id": snapshot, "as_of": now},
        "results": records, "pagination": {"next_cursor": None, "returned": len(records)},
    }
    report = {
        "document_type": "inferencex.collection-report", "schema_version": "inferencex.collection/v1",
        "generated_at": now, "snapshot_id": snapshot,
        "summary": {"inputs": len(inputs), "legacy_results": len(legacy),
                    "contract_results": len(records),
                    "invalid": sum(x["status"] in {"invalid", "unreadable"} for x in inputs)},
        "inputs": inputs,
    }
    return legacy, result_set, report


def write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path)
    parser.add_argument("exp_name")
    parser.add_argument("--contracts-root", type=Path, action="append", default=[])
    parser.add_argument("--schema-dir", type=Path, default=Path(__file__).resolve().parents[1] / "schemas")
    args = parser.parse_args()
    legacy, result_set, report = collect([args.results_dir, *args.contracts_root], args.schema_dir)
    write(Path(f"agg_{args.exp_name}.json"), legacy)
    write(Path("inferencex-result-set.json"), result_set)
    write(Path("inferencex-collection-report.json"), report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

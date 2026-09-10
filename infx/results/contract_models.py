"""Strict Pydantic envelope models and normative JSON Schema validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ConfigDict
from referencing import Registry, Resource

from .contracts import digest_json, matrix_fingerprint


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResultRecordDocument(StrictModel):
    document_type: Literal["inferencex.result-record"]
    schema_version: Literal["inferencex.exchange/v1"]
    generated_at: str
    result: dict[str, Any]


class ResultSetDocument(StrictModel):
    document_type: Literal["inferencex.result-set"]
    schema_version: Literal["inferencex.exchange/v1"]
    generated_at: str
    source: dict[str, Any]
    results: list[dict[str, Any]]
    pagination: dict[str, Any]


class JobManifestDocument(StrictModel):
    document_type: Literal["inferencex.job-manifest"]
    schema_version: Literal["inferencex.exchange/v1"]
    generated_at: str
    run: dict[str, Any]
    plan: dict[str, Any]
    outcome: dict[str, Any]
    source_lock: dict[str, Any]


class RunManifestDocument(StrictModel):
    document_type: Literal["inferencex.run-manifest"]
    schema_version: Literal["inferencex.exchange/v1"]
    generated_at: str
    source_run: dict[str, Any]
    merge_run: dict[str, Any]
    generation: dict[str, Any]
    planned_points: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]


DOCUMENT_MODELS = {
    "inferencex.result-record": ResultRecordDocument,
    "inferencex.result-set": ResultSetDocument,
    "inferencex.job-manifest": JobManifestDocument,
    "inferencex.run-manifest": RunManifestDocument,
}


def _validate_identity_invariants(document: dict[str, Any]) -> None:
    dtype = document["document_type"]
    if dtype == "inferencex.job-manifest":
        if document["outcome"]["plan_id"] != document["plan"]["plan_id"]:
            raise ValueError("Job outcome plan_id must equal plan.plan_id")
        point = document["outcome"]["point_id"]
        if point is not None and point != document["plan"]["point_id"]:
            raise ValueError("Job outcome point_id must equal plan.point_id")
        return
    if dtype != "inferencex.result-record":
        return
    result = document["result"]
    recipe = result["resolved_recipe"]
    expected_matrix = matrix_fingerprint(recipe["resolved_matrix_entry"])
    if recipe["matrix_fingerprint"] != expected_matrix:
        raise ValueError("matrix_fingerprint does not match resolved_matrix_entry")
    point_fingerprint = recipe["point_fingerprint"]
    if result["point_id"] != "infx-point-" + point_fingerprint.removeprefix("sha256:"):
        raise ValueError("point_id does not match point_fingerprint")
    run = result["source_run"]
    record_digest = digest_json({
        "point_id": result["point_id"], "run_id": run["run_id"],
        "run_attempt": run["run_attempt"], "job_id": run["job_id"],
        "job_name": run["job_name"], "result_ordinal": result["result_ordinal"],
    })
    if result["record_id"] != "infx-record-" + record_digest.removeprefix("sha256:"):
        raise ValueError("record_id does not match point/run/job/ordinal identity")
    if result["point"]["active_accelerator_count"] != sum(
        role["physical_accelerators"] for role in result["point"]["roles"]
    ):
        raise ValueError("active_accelerator_count does not equal the role total")
    lock = result["source_lock"]
    expected_lock = digest_json({
        "source_lock": {key: value for key, value in lock.items() if key != "source_lock_digest"},
        "resolved_matrix_entry": recipe["resolved_matrix_entry"],
    })
    if lock["source_lock_digest"] != expected_lock:
        raise ValueError("source_lock_digest does not match source lock and matrix")
    workload = result["workload"]
    behavior = workload.get("behavior_contract")
    protocol = behavior.get("benchmark_protocol") if isinstance(behavior, dict) else None
    if isinstance(protocol, dict):
        for workload_key, protocol_key in (
            ("profile_id", "profile_id"), ("duration_seconds", "duration_seconds"),
            ("benchmark_mode", "mode"),
        ):
            left, right = workload.get(workload_key), protocol.get(protocol_key)
            if left is not None and right is not None and left != right:
                raise ValueError(f"workload.{workload_key} conflicts with behavior contract")


def validate_exchange_document(document: dict[str, Any], schema_dir: Path) -> None:
    """Validate both the strict envelope and every nested normative field."""
    document_type = document.get("document_type")
    model = DOCUMENT_MODELS.get(document_type)
    if model is None:
        raise ValueError(f"Unsupported exchange document type: {document_type!r}")
    model.model_validate(document)
    _validate_identity_invariants(document)

    exchange = json.loads((schema_dir / "inferencex-exchange-contract-v1.json").read_text())
    semantics = json.loads((schema_dir / "inferencex-benchmark-semantics-v1.json").read_text())
    registry = Registry()
    for schema in (exchange, semantics):
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    # Resolve the exchange schema's sibling relative behavior reference locally.
    registry = registry.with_resource(
        exchange["$id"].rsplit("/", 1)[0] + "/inferencex-benchmark-semantics-v1.json",
        Resource.from_contents(semantics),
    )
    errors = sorted(
        Draft202012Validator(
            exchange, registry=registry, format_checker=FormatChecker()
        ).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        details = "; ".join(
            f"/{'/'.join(map(str, error.absolute_path))}: {error.message}"
            for error in errors[:10]
        )
        raise ValueError(f"Exchange document failed schema validation: {details}")

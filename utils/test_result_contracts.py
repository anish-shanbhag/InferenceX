"""Contract tests with hand-worked identity and provenance expectations."""
from __future__ import annotations

import json
from pathlib import Path

from collect_results import collect
from infx.results.contract_models import validate_exchange_document
from infx.results.contracts import (
    build_effective_execution,
    build_plan,
    build_result_record,
    canonical_json_bytes,
    job_manifest,
    iter_matrix_points,
    matrix_fingerprint,
    result_document,
    run_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas"


def fixed_matrix(**updates):
    value = {
        "exp-name": "fixture", "runner": "h100-cw", "model": "org/model",
        "model-prefix": "fixture", "framework": "sglang", "precision": "fp8",
        "image": "registry/image:mutable", "isl": 1024, "osl": 1024,
        "max-model-len": 4096, "tp": 2, "pp": 1, "dcp-size": 1,
        "pcp-size": 1, "ep": 1, "dp-attn": False, "conc": 4,
        "spec-decoding": "none", "disagg": False,
        "recipe-fingerprint": "a" * 64,
    }
    value.update(updates)
    return value


def fixed_row(**updates):
    value = {
        "hw": "h100-cw", "conc": 4, "image": "registry/image:mutable",
        "model": "org/model", "infmax_model_prefix": "fixture",
        "framework": "sglang", "precision": "fp8", "spec_decoding": "none",
        "disagg": False, "recipe_fingerprint": "a" * 64, "isl": 1024,
        "osl": 1024, "is_multinode": False, "tp": 2, "pp": 1,
        "dcp_size": 1, "pcp_size": 1, "ep": 1, "dp_attention": "false",
        "tput_per_gpu": 100.0, "input_tput_per_gpu": 20.0,
        "output_tput_per_gpu": 80.0, "intvty_p50": 50.0,
    }
    value.update(updates)
    return value


def github_env(**updates):
    value = {
        "GITHUB_SHA": "1" * 40, "GITHUB_REPOSITORY": "SemiAnalysisAI/InferenceX",
        "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2", "GITHUB_JOB": "benchmark",
    }
    value.update(updates)
    return value


def test_canonical_json_uses_jcs_order_and_number_thresholds():
    assert canonical_json_bytes({"z": 1e-7, "a": 1e20}) == (
        b'{"a":100000000000000000000,"z":1e-7}'
    )
    assert canonical_json_bytes({"\U0001f600": 1, "\ufffd": 2}).startswith(b'{"\xf0\x9f\x98\x80"')


def test_matrix_identity_does_not_alias_legacy_recipe_fingerprint():
    matrix = fixed_matrix()
    fingerprint = matrix_fingerprint(matrix)
    assert fingerprint != "sha256:" + "a" * 64
    assert matrix_fingerprint({**matrix, "conc": 8}) == fingerprint
    assert matrix_fingerprint({**matrix, "tp": 4}) != fingerprint


def test_execution_receipt_redacts_every_surface_before_digesting():
    receipt = build_effective_execution({"roles": [{
        "role": "aggregated", "component": {"name": "server", "version": "1"},
        "container_role": "server",
        "argv": ["serve", "--api-key", "argv-secret", "--token=inline-secret"],
        "environment": {"SAFE": "yes", "HF_TOKEN": "env-secret"},
        "working_directory": "/work", "mounts": [],
        "resolved_config": {"endpoint": "https://user:password@example.test", "password": "config-secret"},
        "extensions": {"authorization": "Bearer abc"},
    }]})
    serialized = json.dumps(receipt)
    for secret in ("argv-secret", "inline-secret", "env-secret", "password@example", "config-secret", "Bearer abc"):
        assert secret not in serialized
    role = receipt["roles"][0]
    assert role["redacted_environment_names"] == ["HF_TOKEN"]
    assert role["extensions"]["redacted_locations"]


def test_fixed_record_is_schema_valid_and_ordinal_changes_record_id():
    first = build_result_record(fixed_row(), fixed_matrix(), REPO_ROOT, github_env(), result_ordinal=0)
    second = build_result_record(fixed_row(), fixed_matrix(), REPO_ROOT, github_env(), result_ordinal=1)
    assert first["point_id"] == second["point_id"]
    assert first["record_id"] != second["record_id"]
    assert first["extensions"]["legacy_recipe_fingerprint"] == "a" * 64
    assert first["reproducibility"]["status"] == "partial"
    validate_exchange_document(result_document(first), SCHEMA_DIR)


def test_multinode_role_receipt_uses_observed_flat_topology():
    matrix = fixed_matrix(**{
        "scenario-type": "agentic-coding", "isl": 0, "osl": 0,
        "prefill-num-worker": 2, "prefill-tp": 4, "prefill-pp": 2,
        "prefill-dcp-size": 2, "prefill-pcp-size": 1, "prefill-ep": 8,
        "prefill-dp-attn": True, "prefill-hardware": "h200",
        "decode-num-worker": 1, "decode-tp": 8, "decode-pp": 1,
        "decode-dcp-size": 1, "decode-pcp-size": 2, "decode-ep": 8,
        "decode-dp-attn": False, "decode-hardware": "b200", "disagg": True,
        "duration": 3600,
    })
    row = fixed_row(**{
        "scenario_type": "agentic-coding", "is_multinode": True, "disagg": True,
        "num_prefill_gpu": 16, "num_decode_gpu": 16,
        "prefill_num_workers": 2, "prefill_tp": 4, "prefill_pp": 2,
        "prefill_dcp_size": 2, "prefill_pcp_size": 1, "prefill_ep": 8,
        "prefill_dp_attention": "true", "prefill_hw": "h200",
        "decode_num_workers": 1, "decode_tp": 8, "decode_pp": 1,
        "decode_dcp_size": 1, "decode_pcp_size": 2, "decode_ep": 8,
        "decode_dp_attention": "false", "decode_hw": "b200",
        "request_metrics": {"throughput": {"per_gpu": {"total_tput_tps": 12}},
                            "latency": {"full_response_intvty": {"p90": 3}}},
    })
    record = build_result_record(row, matrix, REPO_ROOT, github_env())
    prefill, decode = record["point"]["roles"]
    assert (prefill["tp"], prefill["pp"], prefill["dcp"], prefill["physical_accelerators"]) == (4, 2, 2, 16)
    assert (decode["tp"], decode["pcp"], decode["hardware"], decode["physical_accelerators"]) == (8, 2, "b200", 16)
    assert record["point"]["active_accelerator_count"] == 32
    validate_exchange_document(result_document(record), SCHEMA_DIR)


def test_multinode_aggregate_does_not_invent_decode_accelerators():
    matrix = fixed_matrix(**{
        "scenario-type": "agentic-coding", "conc-list": [2, 8], "conc": None,
        "prefill-num-worker": 1, "prefill-tp": 8, "prefill-pp": 1,
        "prefill-dcp-size": 2, "prefill-pcp-size": 1, "prefill-ep": 8,
        "decode-num-worker": 0, "decode-tp": 0, "decode-pp": 1,
        "decode-dcp-size": 1, "decode-pcp-size": 1, "decode-ep": 0,
        "disagg": False, "duration": 3600,
    })
    points = iter_matrix_points({"multi_node": {"agentic": [matrix]}})
    assert [point["conc"] for _, point in points] == [2, 8]
    row = fixed_row(**{
        "scenario_type": "agentic-coding", "is_multinode": True, "disagg": False,
        "conc": 2, "num_prefill_gpu": 8, "num_decode_gpu": 0,
        "prefill_num_workers": 1, "prefill_tp": 8, "prefill_pp": 1,
        "prefill_dcp_size": 2, "prefill_pcp_size": 1, "prefill_ep": 8,
        "decode_num_workers": 0, "decode_tp": 0, "decode_ep": 0,
        "request_metrics": {"throughput": {"per_gpu": {"total_tput_tps": 12}},
                            "latency": {"full_response_intvty": {"p90": 3}}},
        "behavior_contract": {
            "behavior_schema_version": "inferencex.behavior/v1", "contract_id": None,
            "contract_digest": None, "status": "unknown", "benchmark_protocol": None,
            "request": None, "speculative_decoding": None, "source": None, "extensions": {},
        },
    })
    record = build_result_record(row, {**matrix, "conc": 2}, REPO_ROOT, github_env())
    assert [(role["role"], role["physical_accelerators"]) for role in record["point"]["roles"]] == [("aggregated", 8)]
    assert record["workload"]["behavior_contract"] == row["behavior_contract"]
    validate_exchange_document(result_document(record), SCHEMA_DIR)


def test_planned_and_final_manifests_have_distinct_immutable_lifecycle():
    matrix = fixed_matrix()
    planned = job_manifest(REPO_ROOT, matrix, github_env(), phase="planned")
    record = build_result_record(fixed_row(), matrix, REPO_ROOT, github_env())
    final = job_manifest(REPO_ROOT, matrix, github_env(), phase="final", conclusion="success", result=record)
    assert planned["plan"]["point_id"] is None
    assert planned["outcome"]["point_id"] is None
    assert final["outcome"]["point_id"] == record["point_id"]
    assert final["outcome"]["result_ordinal"] == 0
    validate_exchange_document(planned, SCHEMA_DIR)
    validate_exchange_document(final, SCHEMA_DIR)


def test_collector_keeps_real_agg_filename_and_reports_bad_contract(tmp_path):
    results = tmp_path / "results"
    contracts = tmp_path / "contracts"
    results.mkdir(); contracts.mkdir()
    payload = fixed_row()
    (results / "agg_fixture.json").write_text(json.dumps(payload))
    (contracts / "inferencex-result-record-bad.json").write_text('{"document_type":"inferencex.result-record"}')
    legacy, result_set, report = collect([results, contracts], SCHEMA_DIR)
    assert legacy == [payload]
    assert result_set["results"] == []
    assert report["summary"] == {"inputs": 2, "legacy_results": 1, "contract_results": 0, "invalid": 1}
    assert next(item for item in report["inputs"] if item["status"] == "invalid")["errors"]


def test_run_manifest_marks_unjoined_outcomes_unknown_and_preserves_reuse_source():
    matrix = {"single_node": {"1k1k": [fixed_matrix()]}}
    document = run_manifest(REPO_ROOT, matrix, github_env(
        INFERENCEX_REUSE_SOURCE_RUN_ID="99", INFERENCEX_REUSE_SOURCE_RUN_ATTEMPT="3",
        INFERENCEX_REUSE_SOURCE_HEAD_SHA="2" * 40,
        INFERENCEX_REUSE_SOURCE_RUN_URL="https://github.com/SemiAnalysisAI/InferenceX/actions/runs/99",
    ))
    assert document["source_run"]["head_sha"] == "2" * 40
    assert document["merge_run"]["head_sha"] == "1" * 40
    assert document["outcomes"][0]["status"] == "unknown"
    validate_exchange_document(document, SCHEMA_DIR)

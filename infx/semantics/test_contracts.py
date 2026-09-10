"""Contract tests for AgentX behavior and golden-acceptance semantics."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from infx.semantics.contracts import (
    SemanticsError,
    behavior_digest,
    build_acceptance_injections,
    capture_partial_agentx_behavior,
    load_curve_documents,
    load_document,
    materialize_for_measurement,
    resolve_curve_selection,
    stamp_behavior_document,
    stamp_curve_document,
    write_document,
)
from infx.semantics.models import GoldenAcceptanceCurveDocument, GoldenPoint
from utils.agentic.aggregation.process_agentic_result import attach_behavior_contract
from utils.migrate_golden_curves import LEGACY_DIR, MIGRATIONS


ROOT = Path(__file__).resolve().parents[2]
CURVE_DIR = ROOT / "golden_al_distribution" / "v1"
SCHEMA_PATH = ROOT / "schemas" / "inferencex-benchmark-semantics-v1.json"
SHA_A = "a" * 40
SHA_B = "b" * 40
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64


def _curves() -> list[GoldenAcceptanceCurveDocument]:
    return load_curve_documents(CURVE_DIR)


def _qwen_selection():
    curve_id = "qwen3-5-397b-a17b-nvfp4.mtp.native.speedbench-coding.v1"
    return resolve_curve_selection(
        _curves(),
        curve_id=curve_id,
        model_key="qwen3.5-397b-a17b-nvfp4",
        thinking_state="enabled",
        method="mtp",
        variant="native",
        num_speculative_tokens=3,
        allow_draft=True,
    )


def _resolved_behavior_raw() -> dict:
    selection = _qwen_selection().model_dump(mode="json")
    source = {
        "repository": "https://github.com/SemiAnalysisAI/InferenceX",
        "commit": SHA_A,
        "path": "benchmarks/single_node/agentic/example.sh",
        "blob_object_id": SHA_B,
    }
    injections = [
        item.model_dump(mode="json")
        for item in build_acceptance_injections(
            framework="vllm",
            role="aggregated",
            acceptance_length=selection["acceptance_length"],
            num_speculative_tokens=3,
            native_rejection_method="typical_acceptance_sampler",
        )
    ]
    return {
        "document_type": "inferencex.behavior-contract",
        "schema_version": "inferencex.behavior/v1",
        "generated_at": "2026-09-09T00:00:00Z",
        "behavior": {
            "behavior_schema_version": "inferencex.behavior/v1",
            "contract_id": "pending",
            "contract_digest": DIGEST_A,
            "contract_digest_scope": (
                "planned_behavior_excluding_contract_identity_and_runtime_verification"
            ),
            "status": "resolved",
            "benchmark_protocol": {
                "profile_id": "agentx.canonical.v1",
                "benchmark_id": "inferencex-agentx-mvp",
                "mode": "canonical",
                "client_implementation": {
                    "name": "aiperf",
                    "repository": "https://github.com/SemiAnalysisAI/aiperf",
                    "commit": SHA_A,
                    "entrypoint": "aiperf profile",
                    "package_versions": {"aiperf": "1.0.0"},
                },
                "duration_seconds": 3600,
                "warmup": {
                    "requests_per_lane": 10,
                    "duration_seconds": None,
                    "lane_priming": "trajectory_snapshot_then_one_token_advances",
                    "grace_period_seconds": 1800.0,
                },
                "trace": {
                    "loader": "semianalysis_cc_traces_weka_062126",
                    "corpus": "semianalysisai/cc-traces-weka-062126",
                    "repository": "semianalysisai/cc-traces-weka-062126",
                    "revision": "main",
                    "resolved_commit": SHA_B,
                    "split": "train",
                    "digest": DIGEST_A,
                    "replay_mode": "prerecorded",
                    "timing_mode": "recorded_inter_request_delays",
                    "cache_bust_policy": "first_turn_prefix",
                    "random_seed": 42,
                    "idle_gap_cap_seconds": 300.0,
                    "extensions": {},
                },
                "failure_policy": {
                    "failed_request_fraction_max": 0.1,
                    "early_abort_fraction": 0.1,
                    "transport_timeout_seconds": 900.0,
                },
                "validity_rules": [
                    {
                        "name": "successful_requests",
                        "operator": "gt",
                        "threshold": 0,
                        "unit": "requests",
                    }
                ],
                "unsafe_mode": False,
                "extensions": {},
            },
            "request": {
                "api": "openai.chat.completions",
                "endpoint": "/v1/chat/completions",
                "stream": True,
                "model_field": "qwen3.5",
                "extra_body": {"thinking": True},
                "thinking": {
                    "state": "enabled",
                    "resolution": {"source": "explicit_behavior_profile", "evidence": [source]},
                    "client_encoding": {
                        "surface": "extra_body",
                        "json_pointer": "/thinking",
                        "value": True,
                    },
                    "server_encoding": {
                        "surface": "default_chat_template_kwargs",
                        "field": "enable_thinking",
                        "value": True,
                    },
                },
                "chat_template": {
                    "status": "resolved",
                    "use_chat_template": True,
                    "tokenization_side": "server",
                    "template": {
                        "kind": "tokenizer_default",
                        "repository": "nvidia/Qwen3.5-397B-A17B-NVFP4",
                        "revision": "main",
                        "path": "tokenizer_config.json#/chat_template",
                        "digest": DIGEST_B,
                    },
                    "client_kwargs": {},
                    "server_default_kwargs": {"enable_thinking": True},
                    "add_generation_prompt": True,
                },
                "sampling": {
                    "temperature": 0.6,
                    "top_p": 0.95,
                    "top_k": 20,
                    "min_p": None,
                    "presence_penalty": 0.0,
                    "frequency_penalty": None,
                    "repetition_penalty": None,
                    "seed": 42,
                    "max_output_tokens": 4096,
                    "ignore_eos": False,
                    "stop": None,
                    "extensions": {},
                },
                "headers": [],
                "conversation_routing": {
                    "affinity_required": False,
                    "mechanism": "none",
                    "header_name": None,
                    "session_timeout_seconds": None,
                },
                "tool_choice": None,
                "response_interpretation": {
                    "reasoning_parser": None,
                    "tool_call_parser": None,
                    "automatic_tool_choice": False,
                },
                "token_counting": {
                    "tokenizer": {
                        "repository": "nvidia/Qwen3.5-397B-A17B-NVFP4",
                        "revision": "main",
                        "resolved_commit": SHA_A,
                        "digest": DIGEST_C,
                    },
                    "count_prompt": True,
                    "count_completion": True,
                    "include_reasoning": True,
                },
                "extensions": {},
            },
            "speculative_decoding": {
                "declared_method": "mtp",
                "roles": [
                    {
                        "role": "aggregated",
                        "enabled": True,
                        "method": "mtp",
                        "draft": {
                            "kind": "embedded_heads",
                            "checkpoint": None,
                            "variant": "native",
                            "num_speculative_tokens": 3,
                            "num_speculative_steps": 1,
                            "top_k": None,
                            "extensions": {},
                        },
                        "acceptance": {
                            "mode": "synthetic_golden",
                            "curve_selection": selection,
                            "injections": injections,
                            "runtime_verification": {
                                "status": "not_verified",
                                "observed_acceptance_length": None,
                                "tolerance": None,
                                "evidence": [],
                            },
                        },
                        "effective_server_config_digest": DIGEST_A,
                    }
                ],
                "consistency_status": "consistent",
            },
            "source": {
                "inferencex_commit": SHA_A,
                "sources": [source],
                "resolution_warnings": [],
            },
            "extensions": {},
        },
    }


def test_every_legacy_curve_has_lossless_schema_valid_v1_companion() -> None:
    curves = _curves()
    assert len(curves) == len(MIGRATIONS)
    by_source = {Path(document.curve.source.path).name: document for document in curves}
    assert set(by_source) == set(MIGRATIONS)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for filename, document in by_source.items():
        validator.validate(document.model_dump(mode="json"))
        legacy = yaml.safe_load((LEGACY_DIR / filename).read_text(encoding="utf-8"))
        _, legacy_modes = next(iter(legacy.items()))
        actual = {
            {"enabled": "thinking_on", "disabled": "thinking_off"}[mode.thinking_state]: {
                point.num_speculative_tokens: point.acceptance_length for point in mode.points
            }
            for mode in document.curve.modes
        }
        assert actual == legacy_modes
        assert document.curve.status == "draft"
        assert document.curve.validation.review_status == "pending"


def test_curve_resolution_requires_exact_identity_and_unambiguous_cell() -> None:
    curves = _curves()
    selection = _qwen_selection()
    assert selection.acceptance_length == 3.39

    with pytest.raises(SemanticsError, match="not active"):
        resolve_curve_selection(
            curves,
            curve_id=selection.curve_id,
            model_key=selection.model_key,
            thinking_state="enabled",
            method="mtp",
            variant="native",
            num_speculative_tokens=3,
        )
    for changed in (
        {"model_key": "Qwen/Qwen3.5-397B-A17B-NVFP4"},
        {"method": "eagle3"},
        {"variant": None},
        {"num_speculative_tokens": 99},
    ):
        args = {
            "curve_id": selection.curve_id,
            "model_key": selection.model_key,
            "thinking_state": "enabled",
            "method": "mtp",
            "variant": "native",
            "num_speculative_tokens": 3,
            "allow_draft": True,
        }
        args.update(changed)
        with pytest.raises(SemanticsError, match="no exact"):
            resolve_curve_selection(curves, **args)
    with pytest.raises(SemanticsError, match="ambiguous"):
        resolve_curve_selection(
            [curves[-1], curves[-1]],
            curve_id=curves[-1].curve.curve_id,
            model_key=curves[-1].curve.model_key,
            thinking_state="enabled",
            method=curves[-1].curve.method,
            variant=curves[-1].curve.variant,
            num_speculative_tokens=curves[-1].curve.modes[0].points[0].num_speculative_tokens,
            allow_draft=True,
        )


def test_mode_specific_thinking_template_and_sampling_are_data() -> None:
    document = next(curve for curve in _curves() if curve.curve.model_key.startswith("qwen3.5"))
    modes = {mode.thinking_state: mode for mode in document.curve.modes}
    assert modes["enabled"].sampling.temperature == 0.6
    assert modes["disabled"].sampling.temperature == 0.7
    assert modes["enabled"].chat_template.client_kwargs == {"enable_thinking": True}
    assert modes["disabled"].chat_template.client_kwargs == {"enable_thinking": False}


def test_thinking_contradiction_and_unknown_resolved_template_fail() -> None:
    raw = _resolved_behavior_raw()
    raw["behavior"]["request"]["thinking"]["server_encoding"]["value"] = False
    with pytest.raises(SemanticsError, match="contradict"):
        stamp_behavior_document(raw)

    raw = _resolved_behavior_raw()
    raw["behavior"]["request"]["chat_template"]["status"] = "unknown"
    with pytest.raises(SemanticsError, match="resolved behavior requires resolved"):
        stamp_behavior_document(raw)


def test_framework_and_role_injection_mappings() -> None:
    vllm = build_acceptance_injections(
        framework="vllm", role="aggregated", acceptance_length=3.5,
        num_speculative_tokens=4, native_rejection_method="typical_acceptance_sampler",
    )
    assert [(item.location, item.encoded_value) for item in vllm] == [
        ("/speculative_config/rejection_sample_method", "synthetic"),
        ("/speculative_config/synthetic_acceptance_length", 3.5),
    ]
    assert vllm[0].native_value == "typical_acceptance_sampler"

    sglang = build_acceptance_injections(
        framework="sglang", role="prefill", acceptance_length=3.5,
        num_speculative_tokens=4,
    )
    assert {item.location: item.encoded_value for item in sglang} == {
        "SGLANG_SIMULATE_ACC_LEN": 3.5,
        "SGLANG_SIMULATE_ACC_METHOD": "match-expected",
        "SGLANG_SIMULATE_ACC_TOKEN_MODE": "real-draft-token",
    }
    trtllm = build_acceptance_injections(
        framework="tensorrt-llm", role="decode", acceptance_length=3.5,
        num_speculative_tokens=4,
    )
    assert trtllm[0].transform == "minus_one"
    assert trtllm[0].encoded_value == 2.5
    atom = build_acceptance_injections(
        framework="atom", role="decode", acceptance_length=3.5,
        num_speculative_tokens=4,
    )
    assert atom[0].location == "--spec-decode-acceptance-length"
    assert atom[0].encoded_value == 3.5


def test_behavior_digest_projection_and_accuracy_restoration() -> None:
    throughput = stamp_behavior_document(_resolved_behavior_raw())
    runtime_changed = throughput.model_dump(mode="json")
    verification = runtime_changed["behavior"]["speculative_decoding"]["roles"][0]["acceptance"]["runtime_verification"]
    verification.update(status="verified", observed_acceptance_length=3.4, tolerance=0.1)
    assert behavior_digest(runtime_changed["behavior"]) == throughput.behavior.contract_digest

    semantic_changed = throughput.model_dump(mode="json")
    semantic_changed["behavior"]["request"]["sampling"]["temperature"] = 0.61
    changed = stamp_behavior_document(semantic_changed)
    assert changed.behavior.contract_digest != throughput.behavior.contract_digest
    assert changed.behavior.contract_id != throughput.behavior.contract_id

    accuracy = materialize_for_measurement(throughput, measurement="accuracy")
    acceptance = accuracy.behavior.speculative_decoding.roles[0].acceptance
    assert acceptance.mode == "real"
    assert acceptance.curve_selection is None
    assert all(item.evaluation_scope == "accuracy" for item in acceptance.injections)
    restored = {item.location: item.encoded_value for item in acceptance.injections}
    assert restored["/speculative_config/rejection_sample_method"] == "typical_acceptance_sampler"
    assert restored["/speculative_config/synthetic_acceptance_length"] is None


def test_cross_field_curve_role_and_thinking_mismatches_fail() -> None:
    raw = _resolved_behavior_raw()
    role = raw["behavior"]["speculative_decoding"]["roles"][0]
    role["draft"]["num_speculative_tokens"] = 4
    with pytest.raises(SemanticsError, match="curve K"):
        stamp_behavior_document(raw)

    raw = _resolved_behavior_raw()
    raw["behavior"]["speculative_decoding"]["roles"][0]["acceptance"]["curve_selection"]["thinking_state"] = "disabled"
    with pytest.raises(SemanticsError, match="thinking state"):
        stamp_behavior_document(raw)


@pytest.mark.parametrize(
    ("kind", "values", "derivation", "message"),
    [
        ("empirical_pmf", [0.2, 0.2, 0.2], "counts / total", r"K \+ 1"),
        ("empirical_pmf", [0.2, 0.2, 0.2, 0.2], "counts / total", "sum to 1"),
        ("position_probabilities", [0.9, 0.8], "minimum variance", "contain K"),
        ("position_probabilities", [0.9, 0.7, 0.8], "minimum variance", "non-increasing"),
        ("minimum_variance_pmf", [0.0, 0.5, 0.5, 0.0], None, "require a derivation"),
    ],
)
def test_distribution_shape_and_derivation_invariants(
    kind: str, values: list[float], derivation: str | None, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        GoldenPoint.model_validate(
            {
                "num_speculative_tokens": 3,
                "acceptance_length": 2.5,
                "distribution": {"kind": kind, "values": values, "derivation": derivation},
            },
            strict=True,
        )


def test_active_curve_requires_reviewed_complete_provenance() -> None:
    raw = _curves()[0].model_dump(mode="json")
    raw["curve"]["status"] = "active"
    with pytest.raises(SemanticsError, match="active curves"):
        stamp_curve_document(raw)


def test_partial_runtime_receipt_is_embedded_without_claiming_resolution(tmp_path: Path) -> None:
    partial = capture_partial_agentx_behavior(
        replay_command_digest=DIGEST_A,
        runtime={"framework": "vllm", "thinking_state": None},
        missing_fields=("/request/thinking", "/speculative_decoding/roles"),
    )
    assert partial.behavior.status == "partial"
    assert partial.behavior.contract_digest is not None
    result_dir = tmp_path / "results"
    write_document(partial, result_dir / "behavior_contract.json")
    agg: dict = {}
    attach_behavior_contract(agg, result_dir)
    assert agg["behavior_contract"]["status"] == "partial"
    assert agg["behavior_contract_digest"] == partial.behavior.contract_digest


def test_tampered_curve_digest_is_rejected(tmp_path: Path) -> None:
    raw = _curves()[0].model_dump(mode="json")
    raw["curve"]["modes"][0]["points"][0]["acceptance_length"] += 0.01
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(SemanticsError, match="digest mismatch"):
        load_document(path)

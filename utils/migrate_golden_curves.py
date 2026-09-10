#!/usr/bin/env python3
"""Create reviewed-format v1 companions for the legacy golden AL mappings.

This is deliberately an explicit, one-time migration table. It preserves the
legacy numeric cells without parsing identity or methodology from filenames or
comments. Unknown historical facts stay null and migrated curves remain draft
until their retained artifacts can prove complete provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infx.semantics.contracts import deterministic_curve_id, stamp_curve_document, write_document


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DIR = ROOT / "golden_al_distribution"
OUTPUT_DIR = LEGACY_DIR / "v1"
REPOSITORY = "https://github.com/SemiAnalysisAI/InferenceX"
GENERATED_AT = "2026-09-09T00:00:00Z"


def _sampling(
    *,
    temperature: float | None,
    top_p: float | None = None,
    top_k: int | None = None,
    presence_penalty: float | None = None,
    max_output_tokens: int = 4096,
) -> dict[str, Any]:
    return {
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "min_p": None,
        "presence_penalty": presence_penalty,
        "frequency_penalty": None,
        "repetition_penalty": None,
        "seed": None,
        "max_output_tokens": max_output_tokens,
        "ignore_eos": None,
        "stop": None,
        "extensions": {},
    }


MIGRATIONS: dict[str, dict[str, Any]] = {
    "dsv4_mtp.yaml": {
        "target": "deepseek-ai/DeepSeek-V4-Pro",
        "method": "mtp",
        "variant": "native",
        "draft_kind": "embedded_heads",
        "draft": None,
        "run": 27180633016,
        "source_commit": "ab51b0612d3aec25a08196505334848b83987a45",
        "source_blob": "d8f35396a53623f9dcac616a6b5fd434278e6d0b",
        "collector": "benchmarks/single_node/speedbench/dsv4_fp4_b300_vllm.sh",
        "collector_blob": "b8550a3502a1941efbe5905a16d751b4a61bbb31",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0), {"thinking": True, "reasoning_effort": "high"}),
            "thinking_off": (_sampling(temperature=1.0), {}),
        },
    },
    "dsv4-pro-0813-dspark.yaml": {
        "target": "deepseek-ai/DeepSeek-V4-Pro-DSpark",
        "method": "dspark",
        "variant": "probabilistic-draft",
        "draft_kind": "embedded_heads",
        "draft": None,
        "run": 31742838308,
        "source_commit": "b9c9f925f10a39525b8f08ef0be87996c09f0939",
        "source_blob": "cab002f9d0617a14787b5bf58046e875097b4474",
        "collector": "benchmarks/single_node/speedbench/dsv4dspark_fp4_b300_vllm.sh",
        "collector_blob": "59c138d82a570c4ddf835b072b31cd6935951631",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0), {"thinking": True, "reasoning_effort": "high"}),
        },
    },
    "glm5.2_mtp.yaml": {
        "target": "zai-org/GLM-5.2-FP8",
        "method": "mtp",
        "variant": "native",
        "draft_kind": "embedded_heads",
        "draft": None,
        "run": 28058352479,
        "source_commit": "79aa5d83ee65c5b259cd3cb711f94f6ec7cd8322",
        "source_blob": "afebacac983a3bfddebfdaac828262bace132110",
        "collector": "benchmarks/single_node/speedbench/glm52_fp4_b300_vllm.sh",
        "collector_blob": "f7290fe6b474c1eac284195ebfaa7d01932bea32",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95), {"enable_thinking": True}),
        },
    },
    "kimik2.5_eagle3.yaml": {
        "target": "moonshotai/Kimi-K2.5-NVFP4",
        "method": "eagle3",
        "variant": "mla",
        "draft_kind": "external_checkpoint",
        "draft": "lightseekorg/kimi-k2.5-eagle3-mla",
        "run": 28122195822,
        "source_commit": "ab51b0612d3aec25a08196505334848b83987a45",
        "source_blob": "df702f18ba31e9ecd78043774a31ae4ca01d48f5",
        "collector": "benchmarks/single_node/speedbench/kimik2.5_fp4_b300_vllm.sh",
        "collector_blob": "890c059f9d2845933ca9bf686db3278d6d8b980d",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95), {"thinking": True}),
            "thinking_off": (_sampling(temperature=0.6, top_p=0.95), {"thinking": False}),
        },
    },
    "kimik3_dspark.yaml": {
        "target": "moonshotai/Kimi-K3",
        "method": "dspark",
        "variant": "greedy-draft-default-rejection",
        "draft_kind": "external_checkpoint",
        "draft": "Inferact/Kimi-K3-DSpark",
        "run": 30304797750,
        "source_commit": "ccbb522994ab475c8c54cb37ad965fdf77b8e7c5",
        "source_blob": "1ad725b9210fc3a941b637087785190dd8174b3b",
        "collector": "benchmarks/single_node/speedbench/kimik3_fp4_b300_vllm.sh",
        "collector_blob": "c1ee6c80f31efbbe3ccb1dc0312796be06b3cbc9",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95), {"thinking": True}),
        },
    },
    "kimik3_dspark_probabilistic_sample_method_block_rejection_sample_method.yaml": {
        "target": "moonshotai/Kimi-K3",
        "method": "dspark",
        "variant": "probabilistic-draft-block-rejection",
        "draft_kind": "external_checkpoint",
        "draft": "Inferact/Kimi-K3-DSpark",
        "run": 30316471205,
        "source_commit": "fa3f2a2141c2d8c91c476c9256779eda27b68090",
        "source_blob": "b27aeed0ea0777ae0eee9fc77e7a0c790c6884c1",
        "collector": "benchmarks/single_node/speedbench/kimik3_fp4_b300_vllm_probabilistic_sample_method_block_rejection_sample_method.sh",
        "collector_blob": "68581857351ba6ce9dc098df93151987fe739790",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95), {"thinking": True}),
        },
    },
    "minimaxm3_eagle3.yaml": {
        "target": "MiniMaxAI/MiniMax-M3",
        "method": "eagle3",
        "variant": "mha",
        "draft_kind": "external_checkpoint",
        "draft": "Inferact/MiniMax-M3-EAGLE3",
        "run": 28061204145,
        "source_commit": "ab51b0612d3aec25a08196505334848b83987a45",
        "source_blob": "51de51667818f2df82d787301b83e26fc8ec173b",
        "collector": "benchmarks/single_node/speedbench/minimaxm3_fp4_b300_vllm.sh",
        "collector_blob": "dac39fb5387691f9c89b2a5bc32965714fcd2a50",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95, top_k=40), {"thinking_mode": "enabled"}),
            "thinking_off": (_sampling(temperature=1.0, top_p=0.95, top_k=40), {"thinking_mode": "disabled"}),
        },
    },
    "minimaxm3_eagle3_gqa.yaml": {
        "target": "MiniMaxAI/MiniMax-M3",
        "method": "eagle3",
        "variant": "gqa",
        "draft_kind": "external_checkpoint",
        "draft": "Inferact/MiniMax-M3-EAGLE3",
        "run": 29784780049,
        "source_commit": "85606a70014714b56f284c43bc269735e99b74e2",
        "source_blob": "a8337088bf5e9d1eede0c912d31f122ce14da0ac",
        "collector": "benchmarks/single_node/speedbench/minimaxm3_fp4_b300_vllm.sh",
        "collector_blob": "dac39fb5387691f9c89b2a5bc32965714fcd2a50",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95, top_k=40), {"thinking_mode": "enabled"}),
            "thinking_off": (_sampling(temperature=1.0, top_p=0.95, top_k=40), {"thinking_mode": "disabled"}),
        },
    },
    "qwen3.5_mtp.yaml": {
        "target": "nvidia/Qwen3.5-397B-A17B-NVFP4",
        "method": "mtp",
        "variant": "native",
        "draft_kind": "embedded_heads",
        "draft": None,
        "run": 27317114007,
        "source_commit": "ab51b0612d3aec25a08196505334848b83987a45",
        "source_blob": "f179693046bfe9f4caca27f51456632b88a0c834",
        "collector": "benchmarks/single_node/speedbench/qwen3.5_fp4_b300_vllm.sh",
        "collector_blob": "bf2bda7c8d8b941df4bf224f7f0c5ee0d278361d",
        "modes": {
            "thinking_on": (_sampling(temperature=0.6, top_p=0.95, top_k=20, presence_penalty=0.0), {"enable_thinking": True}),
            "thinking_off": (_sampling(temperature=0.7, top_p=0.8, top_k=20, presence_penalty=1.5), {"enable_thinking": False}),
        },
    },
    "qwen3.8next_mtp.yaml": {
        "target": "Qwen/Qwen3.8-Flash-Next-FP8",
        "method": "mtp",
        "variant": "native-nextn",
        "draft_kind": "embedded_heads",
        "draft": None,
        "run": 33034290269,
        "source_commit": "bc088e0a3d7958505288a6c4785b00116654142f",
        "source_blob": "46800f97e0b9f291753fba5869b19bcb4e16be0e",
        "collector": "benchmarks/single_node/speedbench/qwen3.8next_fp4_b300_vllm.sh",
        "collector_blob": "2faabe5559c41f60eaa99982ca79c45cf1648777",
        "modes": {
            "thinking_on": (_sampling(temperature=1.0, top_p=0.95, top_k=20, presence_penalty=0.0), {"enable_thinking": True}),
        },
    },
}


def _checkpoint(repository: str) -> dict[str, Any]:
    return {
        "repository": repository,
        "revision": None,
        "resolved_commit": None,
        "digest": None,
    }


def _template(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "unknown",
        "use_chat_template": True,
        "tokenization_side": "client",
        "template": {
            "kind": "unknown",
            "repository": None,
            "revision": None,
            "path": None,
            "digest": None,
        },
        "client_kwargs": kwargs,
        "server_default_kwargs": {},
        "add_generation_prompt": None,
    }


def build_document(filename: str, metadata: dict[str, Any]) -> dict[str, Any]:
    legacy_path = LEGACY_DIR / filename
    legacy = yaml.safe_load(legacy_path.read_text(encoding="utf-8"))
    if not isinstance(legacy, dict) or len(legacy) != 1:
        raise ValueError(f"{filename}: expected exactly one model key")
    model_key, legacy_modes = next(iter(legacy.items()))
    if not isinstance(legacy_modes, dict):
        raise ValueError(f"{filename}: expected thinking-mode mapping")

    modes = []
    for legacy_name, (sampling, kwargs) in metadata["modes"].items():
        values = legacy_modes.get(legacy_name)
        if not isinstance(values, dict):
            raise ValueError(f"{filename}: missing declared mode {legacy_name}")
        modes.append(
            {
                "thinking_state": {"thinking_on": "enabled", "thinking_off": "disabled"}[legacy_name],
                "sampling": sampling,
                "chat_template": _template(kwargs),
                "points": [
                    {
                        "num_speculative_tokens": int(level),
                        "acceptance_length": float(acceptance_length),
                        "distribution": {
                            "kind": "mean_only",
                            "values": [],
                            "derivation": None,
                        },
                    }
                    for level, acceptance_length in values.items()
                ],
            }
        )

    source = {
        "repository": REPOSITORY,
        "commit": metadata["source_commit"],
        "path": f"golden_al_distribution/{filename}",
        "blob_object_id": metadata["source_blob"],
    }
    draft_checkpoint = _checkpoint(metadata["draft"]) if metadata["draft"] else None
    curve_id = deterministic_curve_id(
        model_key=model_key,
        method=metadata["method"],
        variant=metadata["variant"],
        category="coding",
    )
    return {
        "document_type": "inferencex.golden-acceptance-curve",
        "schema_version": "inferencex.golden-acceptance/v1",
        "generated_at": GENERATED_AT,
        "curve": {
            "curve_schema_version": "inferencex.golden-acceptance/v1",
            "curve_id": curve_id,
            "curve_digest": "sha256:" + "0" * 64,
            "status": "draft",
            "model_key": model_key,
            "target_checkpoint": _checkpoint(metadata["target"]),
            "draft": {
                "kind": metadata["draft_kind"],
                "checkpoint": draft_checkpoint,
                "variant": metadata["variant"],
                "num_speculative_tokens": None,
                "num_speculative_steps": None,
                "top_k": None,
                "extensions": {},
            },
            "method": metadata["method"],
            "variant": metadata["variant"],
            "modes": modes,
            "collection": {
                "dataset": {
                    "repository": "nvidia/SPEED-Bench",
                    "revision": None,
                    "resolved_commit": None,
                    "split": "Qualitative",
                    "digest": None,
                },
                "category": "coding",
                "prompt_count": 80,
                "output_length": 4096,
                "formula": "1 + accepted_draft_tokens / verification_steps",
                "statistic": "mean_acceptance_length",
                "rounding_decimals": 2,
                "framework": "vllm",
                "framework_version": None,
                "image": {"reference": "unknown", "manifest_digest": None},
                "hardware": "NVIDIA B300",
                "collector": {
                    "repository": REPOSITORY,
                    "commit": metadata["source_commit"],
                    "path": metadata["collector"],
                    "blob_object_id": metadata["collector_blob"],
                },
                "workflow_run_url": f"{REPOSITORY}/actions/runs/{metadata['run']}",
                "workflow_run_id": metadata["run"],
                "workflow_run_attempt": 1,
                "artifacts": [
                    {
                        "name": "speedbench-reference-al",
                        "url": None,
                        "digest": None,
                    }
                ],
            },
            "source": source,
            "validation": {
                "review_status": "pending",
                "reviewed_by": [],
                "reviewed_at": None,
                "notes": [
                    "Mechanically migrated from the cited legacy curve without changing numeric cells.",
                    "Checkpoint, dataset, image, tokenizer/template, and retained-artifact digests require review before activation.",
                ],
            },
        },
    }


def main() -> int:
    legacy_names = {path.name for path in LEGACY_DIR.glob("*.yaml")}
    if legacy_names != set(MIGRATIONS):
        missing = sorted(legacy_names - set(MIGRATIONS))
        stale = sorted(set(MIGRATIONS) - legacy_names)
        raise SystemExit(f"migration inventory mismatch: missing={missing}, stale={stale}")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    expected_outputs: set[Path] = set()
    for filename, metadata in MIGRATIONS.items():
        document = stamp_curve_document(build_document(filename, metadata))
        output = OUTPUT_DIR / f"{document.curve.curve_id}.json"
        write_document(document, output)
        expected_outputs.add(output)
    stale_outputs = set(OUTPUT_DIR.glob("*.json")) - expected_outputs
    if stale_outputs:
        raise SystemExit(f"unexpected v1 curve documents: {sorted(map(str, stale_outputs))}")
    print(f"wrote {len(expected_outputs)} curve documents to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

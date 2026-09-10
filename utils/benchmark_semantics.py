#!/usr/bin/env python3
"""CLI for InferenceX behavior contracts and golden-acceptance curves."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infx.semantics.contracts import (
    SemanticsError,
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
from infx.semantics.models import BehaviorContractDocument


def _write_stdout(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def _validate(args: argparse.Namespace) -> int:
    for path in args.paths:
        load_document(path)
        print(f"valid: {path}")
    return 0


def _stamp(args: argparse.Namespace) -> int:
    source = Path(args.path)
    text = source.read_text(encoding="utf-8")
    if source.suffix == ".json":
        raw = json.loads(text)
    else:
        import yaml

        raw = yaml.safe_load(text)
    kind = raw.get("document_type") if isinstance(raw, dict) else None
    if kind == "inferencex.golden-acceptance-curve":
        document = stamp_curve_document(raw)
    elif kind == "inferencex.behavior-contract":
        document = stamp_behavior_document(raw)
    else:
        raise SemanticsError(f"unsupported document_type: {kind!r}")
    write_document(document, args.output)
    return 0


def _resolve_curve(args: argparse.Namespace) -> int:
    selection = resolve_curve_selection(
        load_curve_documents(args.directory),
        curve_id=args.curve_id,
        model_key=args.model_key,
        thinking_state=args.thinking_state,
        method=args.method,
        variant=args.variant,
        num_speculative_tokens=args.num_speculative_tokens,
        allow_draft=args.allow_draft,
    )
    _write_stdout(selection.model_dump(mode="json"))
    return 0


def _injections(args: argparse.Namespace) -> int:
    values = build_acceptance_injections(
        framework=args.framework,
        role=args.role,
        acceptance_length=args.acceptance_length,
        num_speculative_tokens=args.num_speculative_tokens,
        native_rejection_method=args.native_rejection_method,
    )
    _write_stdout([value.model_dump(mode="json") for value in values])
    return 0


def _materialize(args: argparse.Namespace) -> int:
    document = load_document(args.path)
    if not isinstance(document, BehaviorContractDocument):
        raise SemanticsError(f"{args.path} is not a behavior contract")
    effective = materialize_for_measurement(document, measurement=args.measurement)
    write_document(effective, args.output)
    return 0


def _capture_partial(args: argparse.Namespace) -> int:
    command = Path(args.replay_command_file).read_bytes()
    command_digest = f"sha256:{hashlib.sha256(command).hexdigest()}"
    runtime = {
        "measurement_semantics": args.measurement,
        "benchmark_mode": "fast" if os.environ.get("AIPERF_EXPERIMENTAL_FAST") == "1" else "canonical",
        "model": os.environ.get("MODEL"),
        "served_model_name": os.environ.get("SERVED_MODEL_NAME"),
        "model_prefix": os.environ.get("MODEL_PREFIX"),
        "framework": os.environ.get("FRAMEWORK"),
        "speculative_method": os.environ.get("SPEC_DECODING", "none"),
        "concurrency": int(os.environ.get("CONC", "0")),
        "duration_seconds": int(os.environ.get("DURATION", "0")),
        "trace_loader": os.environ.get("INFERENCEX_AGENTX_TRACE_LOADER"),
        "trace_dataset": os.environ.get("INFERENCEX_AGENTX_TRACE_DATASET"),
        "thinking_state": os.environ.get("INFERENCEX_THINKING_STATE"),
        "acceptance_mode": os.environ.get("INFERENCEX_ACCEPTANCE_MODE"),
    }
    document = capture_partial_agentx_behavior(
        replay_command_digest=command_digest,
        runtime=runtime,
        missing_fields=(
            "/benchmark_protocol/client_implementation/commit",
            "/benchmark_protocol/trace/resolved_commit",
            "/benchmark_protocol/trace/digest",
            "/request/thinking",
            "/request/chat_template",
            "/request/sampling",
            "/speculative_decoding/roles",
        ),
    )
    write_document(document, args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="strictly validate document(s) and digests")
    validate.add_argument("paths", nargs="+")
    validate.set_defaults(func=_validate)

    stamp = commands.add_parser("stamp", help="calculate digest/ID and export canonical JSON")
    stamp.add_argument("path")
    stamp.add_argument("--output", required=True)
    stamp.set_defaults(func=_stamp)

    resolve = commands.add_parser("resolve-curve", help="resolve one exact curve cell")
    resolve.add_argument("--directory", default="golden_al_distribution/v1")
    resolve.add_argument("--curve-id", required=True)
    resolve.add_argument("--model-key", required=True)
    resolve.add_argument("--thinking-state", choices=("enabled", "disabled"), required=True)
    resolve.add_argument(
        "--method", choices=("mtp", "eagle", "eagle3", "draft_model", "dspark", "other"), required=True
    )
    resolve.add_argument("--variant")
    resolve.add_argument("--num-speculative-tokens", type=int, required=True)
    resolve.add_argument("--allow-draft", action="store_true")
    resolve.set_defaults(func=_resolve_curve)

    inject = commands.add_parser("injections", help="render typed framework/role injections")
    inject.add_argument("--framework", choices=("vllm", "sglang", "tensorrt-llm", "atom"), required=True)
    inject.add_argument("--role", choices=("aggregated", "prefill", "decode"), required=True)
    inject.add_argument("--acceptance-length", type=float, required=True)
    inject.add_argument("--num-speculative-tokens", type=int, required=True)
    inject.add_argument("--native-rejection-method")
    inject.set_defaults(func=_injections)

    materialize = commands.add_parser(
        "materialize", help="export exact throughput or real-acceptance accuracy behavior"
    )
    materialize.add_argument("path")
    materialize.add_argument("--measurement", choices=("throughput", "accuracy"), required=True)
    materialize.add_argument("--output", required=True)
    materialize.set_defaults(func=_materialize)

    capture = commands.add_parser(
        "capture-partial",
        help="emit an explicit partial receipt for a legacy AgentX job",
    )
    capture.add_argument("--replay-command-file", required=True)
    capture.add_argument("--measurement", choices=("throughput", "accuracy"), required=True)
    capture.add_argument("--output", required=True)
    capture.set_defaults(func=_capture_partial)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.func(args)
    except (SemanticsError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

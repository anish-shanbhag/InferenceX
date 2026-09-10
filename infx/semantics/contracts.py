"""Load, identify, resolve, and materialize AgentX semantics documents."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

import rfc8785
import yaml
from pydantic import TypeAdapter, ValidationError

from .models import (
    AcceptanceInjection,
    BehaviorContract,
    BehaviorContractDocument,
    CurveSelection,
    GoldenAcceptanceCurve,
    GoldenAcceptanceCurveDocument,
    SemanticsDocument,
)


_DOCUMENT_ADAPTER = TypeAdapter(BehaviorContractDocument | GoldenAcceptanceCurveDocument)
_SAFE_ID_PART = re.compile(r"[^a-z0-9]+")


class SemanticsError(ValueError):
    """A semantics document is invalid, ambiguous, or inconsistent."""


def _canonical_sha256(value: Any) -> str:
    try:
        encoded = rfc8785.dumps(value)
    except (rfc8785.CanonicalizationError, TypeError) as exc:
        raise SemanticsError(f"value is not RFC 8785 canonicalizable: {exc}") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _as_json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return copy.deepcopy(value)


def curve_digest(curve: GoldenAcceptanceCurve | Mapping[str, Any]) -> str:
    """Hash the full curve with only ``curve_digest`` omitted."""

    projection = _as_json_value(curve)
    projection.pop("curve_digest", None)
    return _canonical_sha256(projection)


def behavior_digest_projection(
    behavior: BehaviorContract | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the explicit pre-run projection covered by ``contract_digest``.

    ``contract_id`` is derived from the resulting digest and is therefore not
    itself in the projection. Runtime verification is measurement evidence,
    not planned behavior, and is also excluded. Everything else—including
    golden cell identity and the complete injection plan—is covered.
    """

    projection = _as_json_value(behavior)
    projection.pop("contract_digest", None)
    projection.pop("contract_id", None)
    speculative = projection.get("speculative_decoding")
    if isinstance(speculative, dict):
        for role in speculative.get("roles", []):
            if isinstance(role, dict):
                acceptance = role.get("acceptance")
                if isinstance(acceptance, dict):
                    acceptance.pop("runtime_verification", None)
    return cast(dict[str, Any], projection)


def behavior_digest(behavior: BehaviorContract | Mapping[str, Any]) -> str:
    """Hash the documented pre-run behavior projection."""

    return _canonical_sha256(behavior_digest_projection(behavior))


def deterministic_contract_id(
    behavior: BehaviorContract | Mapping[str, Any], contract_digest: str | None = None
) -> str:
    """Build a stable human-readable ID from profile plus planned digest."""

    value = _as_json_value(behavior)
    profile = ((value.get("benchmark_protocol") or {}).get("profile_id") or "agentx")
    profile_part = _SAFE_ID_PART.sub("-", str(profile).lower()).strip("-") or "agentx"
    digest = contract_digest or behavior_digest(value)
    return f"{profile_part}.{digest.removeprefix('sha256:')[:16]}.v1"


def deterministic_curve_id(
    *, model_key: str, method: str, variant: str | None, category: str
) -> str:
    """Build a stable curve ID from exact semantic identity fields."""

    parts = (model_key, method, variant or "default", f"speedbench-{category}", "v1")
    return ".".join(_SAFE_ID_PART.sub("-", part.lower()).strip("-") for part in parts)


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SemanticsError(f"cannot read {path}: {exc}") from exc
    try:
        raw = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SemanticsError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SemanticsError(f"{path} must contain one object document")
    return raw


def load_document(path: str | Path, *, verify_digest: bool = True) -> SemanticsDocument:
    """Load one strict YAML/JSON document and verify its content digest."""

    source = Path(path)
    raw = _read_mapping(source)
    try:
        document = _DOCUMENT_ADAPTER.validate_python(raw, strict=True)
    except ValidationError as exc:
        raise SemanticsError(f"invalid semantics document {source}:\n{exc}") from exc
    if verify_digest:
        validate_document_digest(document)
    return document


def validate_document_digest(document: SemanticsDocument) -> None:
    """Reject a document whose declared digest differs from its contents."""

    if isinstance(document, GoldenAcceptanceCurveDocument):
        actual = curve_digest(document.curve)
        if document.curve.curve_digest != actual:
            raise SemanticsError(
                f"curve digest mismatch: declared {document.curve.curve_digest}, actual {actual}"
            )
        return

    behavior = document.behavior
    if behavior.contract_digest is None:
        if behavior.status == "resolved":
            raise SemanticsError("resolved behavior is missing contract_digest")
        return
    actual = behavior_digest(behavior)
    if behavior.contract_digest != actual:
        raise SemanticsError(
            f"behavior digest mismatch: declared {behavior.contract_digest}, actual {actual}"
        )
    expected_id = deterministic_contract_id(behavior, actual)
    if behavior.contract_id != expected_id:
        raise SemanticsError(
            f"contract ID mismatch: declared {behavior.contract_id}, expected {expected_id}"
        )


def stamp_curve_document(raw: Mapping[str, Any]) -> GoldenAcceptanceCurveDocument:
    """Calculate a curve digest and return a validated document."""

    stamped = copy.deepcopy(dict(raw))
    curve = stamped.get("curve")
    if not isinstance(curve, dict):
        raise SemanticsError("curve document is missing object field 'curve'")
    curve["curve_digest"] = curve_digest(curve)
    try:
        document = GoldenAcceptanceCurveDocument.model_validate(stamped, strict=True)
    except ValidationError as exc:
        raise SemanticsError(f"invalid curve document:\n{exc}") from exc
    validate_document_digest(document)
    return document


def stamp_behavior_document(raw: Mapping[str, Any]) -> BehaviorContractDocument:
    """Calculate a planned behavior digest and deterministic contract ID."""

    stamped = copy.deepcopy(dict(raw))
    behavior = stamped.get("behavior")
    if not isinstance(behavior, dict):
        raise SemanticsError("behavior document is missing object field 'behavior'")
    digest = behavior_digest(behavior)
    behavior["contract_digest"] = digest
    behavior["contract_id"] = deterministic_contract_id(behavior, digest)
    try:
        document = BehaviorContractDocument.model_validate(stamped, strict=True)
    except ValidationError as exc:
        raise SemanticsError(f"invalid behavior document:\n{exc}") from exc
    validate_document_digest(document)
    return document


def write_document(document: SemanticsDocument, output: str | Path) -> None:
    """Atomically write canonical field content as readable JSON."""

    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(document.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)


def load_curve_documents(directory: str | Path) -> list[GoldenAcceptanceCurveDocument]:
    """Load every v1 curve document without interpreting its filename."""

    root = Path(directory)
    paths = sorted((*root.glob("*.json"), *root.glob("*.yaml"), *root.glob("*.yml")))
    documents: list[GoldenAcceptanceCurveDocument] = []
    ids: set[str] = set()
    for path in paths:
        document = load_document(path)
        if not isinstance(document, GoldenAcceptanceCurveDocument):
            raise SemanticsError(f"{path} is not a golden-acceptance curve")
        if document.curve.curve_id in ids:
            raise SemanticsError(f"duplicate curve_id: {document.curve.curve_id}")
        ids.add(document.curve.curve_id)
        documents.append(document)
    return documents


def resolve_curve_selection(
    curves: Iterable[GoldenAcceptanceCurveDocument],
    *,
    curve_id: str,
    model_key: str,
    thinking_state: Literal["enabled", "disabled"],
    method: Literal["mtp", "eagle", "eagle3", "draft_model", "dspark", "other"],
    variant: str | None,
    num_speculative_tokens: int,
    allow_draft: bool = False,
) -> CurveSelection:
    """Resolve one exact curve cell; never normalize aliases or inspect paths."""

    matches: list[tuple[GoldenAcceptanceCurveDocument, float]] = []
    for document in curves:
        curve = document.curve
        if (
            curve.curve_id != curve_id
            or curve.model_key != model_key
            or curve.method != method
            or curve.variant != variant
        ):
            continue
        if curve.status != "active" and not allow_draft:
            raise SemanticsError(f"curve {curve_id} is {curve.status}, not active")
        for mode in curve.modes:
            if mode.thinking_state != thinking_state:
                continue
            for point in mode.points:
                if point.num_speculative_tokens == num_speculative_tokens:
                    matches.append((document, point.acceptance_length))

    if not matches:
        raise SemanticsError(
            "no exact golden curve cell for "
            f"curve_id={curve_id!r}, model_key={model_key!r}, method={method!r}, "
            f"variant={variant!r}, thinking_state={thinking_state!r}, "
            f"num_speculative_tokens={num_speculative_tokens}"
        )
    if len(matches) != 1:
        raise SemanticsError(f"ambiguous exact golden curve selection for {curve_id!r}")
    document, acceptance_length = matches[0]
    curve = document.curve
    return CurveSelection(
        curve_id=curve.curve_id,
        curve_digest=curve.curve_digest,
        source=curve.source,
        model_key=curve.model_key,
        thinking_state=thinking_state,
        method=method,
        variant=variant,
        num_speculative_tokens=num_speculative_tokens,
        acceptance_length=acceptance_length,
        statistic=curve.collection.statistic,
        rounding_decimals=curve.collection.rounding_decimals,
    )


def build_acceptance_injections(
    *,
    framework: Literal["vllm", "sglang", "tensorrt-llm", "atom"],
    role: Literal["aggregated", "prefill", "decode"],
    acceptance_length: float,
    num_speculative_tokens: int,
    native_rejection_method: str | None = None,
) -> list[AcceptanceInjection]:
    """Encode one semantic golden AL on a specific framework/role surface."""

    if not 1 <= acceptance_length <= num_speculative_tokens + 1:
        raise SemanticsError("acceptance length must be in [1, K + 1]")
    common = {"role": role, "framework": framework, "evaluation_scope": "throughput"}
    if framework == "vllm":
        return [
            AcceptanceInjection(
                **common,
                surface="config_field",
                location="/speculative_config/rejection_sample_method",
                transform="other",
                encoded_value="synthetic",
                native_value=native_rejection_method,
            ),
            AcceptanceInjection(
                **common,
                surface="config_field",
                location="/speculative_config/synthetic_acceptance_length",
                transform="identity",
                encoded_value=acceptance_length,
                native_value=None,
            ),
        ]
    if framework == "sglang":
        values: tuple[tuple[str, str | float, str], ...] = (
            ("SGLANG_SIMULATE_ACC_LEN", acceptance_length, "identity"),
            ("SGLANG_SIMULATE_ACC_METHOD", "match-expected", "other"),
            ("SGLANG_SIMULATE_ACC_TOKEN_MODE", "real-draft-token", "other"),
        )
        return [
            AcceptanceInjection(
                **common,
                surface="environment",
                location=name,
                transform=cast(Any, transform),
                encoded_value=value,
                native_value=None,
            )
            for name, value, transform in values
        ]
    if framework == "tensorrt-llm":
        return [
            AcceptanceInjection(
                **common,
                surface="environment",
                location="TLLM_SPEC_DECODE_FORCE_NUM_ACCEPTED_TOKENS",
                transform="minus_one",
                encoded_value=acceptance_length - 1,
                native_value=None,
            )
        ]
    return [
        AcceptanceInjection(
            **common,
            surface="cli_argument",
            location="--spec-decode-acceptance-length",
            transform="identity",
            encoded_value=acceptance_length,
            native_value=None,
        )
    ]


def materialize_for_measurement(
    document: BehaviorContractDocument,
    *,
    measurement: Literal["throughput", "accuracy"],
) -> BehaviorContractDocument:
    """Produce the effective throughput or real-acceptance accuracy receipt."""

    raw = document.model_dump(mode="json")
    speculative = raw["behavior"].get("speculative_decoding")
    if not isinstance(speculative, dict):
        return stamp_behavior_document(raw)
    for role in speculative["roles"]:
        acceptance = role["acceptance"]
        if measurement == "throughput":
            if acceptance["mode"] == "real" and acceptance["injections"]:
                raise SemanticsError("throughput receipt contains accuracy restoration injections")
            continue
        if acceptance["mode"] != "synthetic_golden":
            continue
        restoration: list[dict[str, Any]] = []
        for injection in acceptance["injections"]:
            # Null means the control did not exist before synthetic injection;
            # restoring it is represented as removing the field/environment key.
            restoration.append(
                {
                    "role": injection["role"],
                    "framework": injection["framework"],
                    "surface": injection["surface"],
                    "location": injection["location"],
                    "transform": "other",
                    "encoded_value": injection["native_value"],
                    "evaluation_scope": "accuracy",
                    "native_value": injection["encoded_value"],
                }
            )
        acceptance.update(
            mode="real",
            curve_selection=None,
            injections=restoration,
            runtime_verification={
                "status": "not_verified",
                "observed_acceptance_length": None,
                "tolerance": None,
                "evidence": [],
            },
        )
    raw["behavior"].setdefault("extensions", {})["measurement_semantics"] = measurement
    return stamp_behavior_document(raw)


def capture_partial_agentx_behavior(
    *,
    replay_command_digest: str,
    runtime: Mapping[str, Any],
    missing_fields: Iterable[str],
) -> BehaviorContractDocument:
    """Create an honest fallback receipt for a legacy, unprofiled AgentX job.

    New jobs should supply a resolved behavior contract. This fallback prevents
    absence from being mistaken for a default while preserving a stable digest
    and the non-secret facts available centrally in ``benchmark_lib.sh``.
    """

    raw = {
        "document_type": "inferencex.behavior-contract",
        "schema_version": "inferencex.behavior/v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "behavior": {
            "behavior_schema_version": "inferencex.behavior/v1",
            "contract_id": None,
            "contract_digest": None,
            "contract_digest_scope": (
                "planned_behavior_excluding_contract_identity_and_runtime_verification"
            ),
            "status": "partial",
            "benchmark_protocol": None,
            "request": None,
            "speculative_decoding": None,
            "source": None,
            "extensions": {
                "fallback_kind": "legacy_runtime_snapshot",
                "missing_fields": sorted(set(missing_fields)),
                "replay_command_digest": replay_command_digest,
                "runtime": dict(runtime),
            },
        },
    }
    return stamp_behavior_document(raw)

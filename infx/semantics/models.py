"""Strict Pydantic models for the InferenceX benchmark-semantics v1 schema.

The checked-in JSON Schema is the wire-format authority.  These models give
producers and consumers one typed construction/loading path and add the
cross-field invariants that JSON Schema cannot express concisely.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
GitObjectId = Annotated[str, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
JsonScalar: TypeAlias = str | int | float | bool | None
ThinkingState = Literal["enabled", "disabled", "not_applicable", "unknown"]
SpeculativeMethod = Literal[
    "none", "mtp", "eagle", "eagle3", "draft_model", "dspark", "other", "unknown"
]


class StrictModel(BaseModel):
    """Reject unknown fields and implicit scalar coercion."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class SourcePointer(StrictModel):
    repository: str = Field(min_length=1)
    commit: GitObjectId
    path: str = Field(min_length=1)
    blob_object_id: GitObjectId


class ArtifactPointer(StrictModel):
    name: str = Field(min_length=1)
    url: str | None
    digest: Digest | None


class CheckpointIdentity(StrictModel):
    repository: str = Field(min_length=1)
    revision: str | None
    resolved_commit: str | None
    digest: Digest | None


class SamplingParameters(StrictModel):
    temperature: float | None = Field(ge=0)
    top_p: float | None = Field(ge=0, le=1)
    top_k: int | None = Field(ge=-1)
    min_p: float | None = Field(ge=0, le=1)
    presence_penalty: float | None
    frequency_penalty: float | None
    repetition_penalty: float | None = Field(gt=0)
    seed: int | None
    max_output_tokens: int | None = Field(ge=1)
    ignore_eos: bool | None
    stop: list[str | int] | None
    extensions: dict[str, Any] = Field(default_factory=dict)


class TemplateIdentity(StrictModel):
    kind: Literal["tokenizer_default", "file", "inline", "none", "unknown"]
    repository: str | None
    revision: str | None
    path: str | None
    digest: Digest | None

    @model_validator(mode="after")
    def validate_identity(self) -> "TemplateIdentity":
        if self.kind == "none" and any(
            value is not None
            for value in (self.repository, self.revision, self.path, self.digest)
        ):
            raise ValueError("a 'none' template cannot carry source identity")
        if self.kind in {"file", "inline"} and self.digest is None:
            raise ValueError(f"a {self.kind} template requires a content digest")
        return self


class ChatTemplateContract(StrictModel):
    status: Literal["resolved", "unknown"]
    use_chat_template: bool | None
    tokenization_side: Literal["client", "server", "both", "unknown"]
    template: TemplateIdentity
    client_kwargs: dict[str, Any]
    server_default_kwargs: dict[str, Any]
    add_generation_prompt: bool | None

    @model_validator(mode="after")
    def validate_resolved(self) -> "ChatTemplateContract":
        if self.status == "resolved":
            if self.use_chat_template is None or self.tokenization_side == "unknown":
                raise ValueError("a resolved chat template needs explicit use and tokenization side")
            if self.template.kind == "unknown":
                raise ValueError("a resolved chat template cannot have unknown identity")
            if self.use_chat_template and self.template.kind == "none":
                raise ValueError("use_chat_template=true requires a template")
        return self


class ThinkingResolution(StrictModel):
    source: Literal[
        "explicit_matrix",
        "explicit_behavior_profile",
        "explicit_request",
        "locked_revision_default",
        "server_default",
        "not_applicable",
        "unknown",
    ]
    evidence: list[SourcePointer]


class ClientThinkingEncoding(StrictModel):
    surface: Literal["extra_body", "chat_template_kwargs", "none", "unknown"]
    json_pointer: str | None
    value: JsonScalar


class ServerThinkingEncoding(StrictModel):
    surface: Literal[
        "default_chat_template_kwargs", "server_flag", "environment", "none", "unknown"
    ]
    field: str | None
    value: JsonScalar


def _semantic_bool(value: JsonScalar) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "on", "enabled", "high"}:
            return True
        if normalized in {"false", "0", "off", "disabled", "none"}:
            return False
    return None


class ThinkingContract(StrictModel):
    state: ThinkingState
    resolution: ThinkingResolution
    client_encoding: ClientThinkingEncoding
    server_encoding: ServerThinkingEncoding

    @model_validator(mode="after")
    def reject_contradictory_encodings(self) -> "ThinkingContract":
        encoded = [
            value
            for value in (
                _semantic_bool(self.client_encoding.value),
                _semantic_bool(self.server_encoding.value),
            )
            if value is not None
        ]
        if len(set(encoded)) > 1:
            raise ValueError("client and server thinking encodings contradict each other")
        expected = {"enabled": True, "disabled": False}.get(self.state)
        if expected is not None and encoded and encoded[0] != expected:
            raise ValueError("thinking encoding contradicts the resolved state")
        return self


class RequestHeader(StrictModel):
    name: str = Field(min_length=1)
    value_source: str = Field(min_length=1)
    semantic_role: Literal["conversation_affinity", "routing", "content", "other"]


class ConversationRouting(StrictModel):
    affinity_required: bool | None
    mechanism: Literal[
        "correlation_id_header", "aiperf_legacy", "router_native", "none", "unknown"
    ]
    header_name: str | None
    session_timeout_seconds: float | None = Field(ge=0)


class ResponseInterpretation(StrictModel):
    reasoning_parser: str | None
    tool_call_parser: str | None
    automatic_tool_choice: bool | None


class TokenCounting(StrictModel):
    tokenizer: CheckpointIdentity
    count_prompt: bool
    count_completion: bool
    include_reasoning: bool


class RequestContract(StrictModel):
    api: Literal["openai.chat.completions", "openai.responses", "custom"]
    endpoint: str = Field(min_length=1)
    stream: bool
    model_field: str = Field(min_length=1)
    extra_body: dict[str, Any]
    thinking: ThinkingContract
    chat_template: ChatTemplateContract
    sampling: SamplingParameters
    headers: list[RequestHeader]
    conversation_routing: ConversationRouting
    tool_choice: str | dict[str, Any] | None
    response_interpretation: ResponseInterpretation
    token_counting: TokenCounting
    extensions: dict[str, Any] = Field(default_factory=dict)


class TraceProtocol(StrictModel):
    loader: str = Field(min_length=1)
    corpus: str = Field(min_length=1)
    repository: str | None
    revision: str | None
    resolved_commit: str | None
    split: str | None
    digest: Digest | None
    replay_mode: Literal["prerecorded", "live", "hybrid", "unknown"]
    timing_mode: str = Field(min_length=1)
    cache_bust_policy: str = Field(min_length=1)
    random_seed: int | None
    idle_gap_cap_seconds: float | None = Field(ge=0)
    extensions: dict[str, Any] = Field(default_factory=dict)


class WarmupProtocol(StrictModel):
    requests_per_lane: int = Field(ge=0)
    duration_seconds: float | None = Field(ge=0)
    lane_priming: str = Field(min_length=1)
    grace_period_seconds: float | None = Field(ge=0)


class ValidityRule(StrictModel):
    name: str = Field(min_length=1)
    operator: Literal["lt", "lte", "gt", "gte", "eq", "present"]
    threshold: JsonScalar
    unit: str | None


class ClientImplementation(StrictModel):
    name: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    commit: GitObjectId
    entrypoint: str = Field(min_length=1)
    package_versions: dict[str, str]


class FailurePolicy(StrictModel):
    failed_request_fraction_max: float = Field(ge=0, le=1)
    early_abort_fraction: float | None = Field(ge=0, le=1)
    transport_timeout_seconds: float | None = Field(ge=0)


class BenchmarkProtocol(StrictModel):
    profile_id: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    mode: Literal["canonical", "fast", "diagnostic"]
    client_implementation: ClientImplementation
    duration_seconds: int = Field(ge=1)
    warmup: WarmupProtocol
    trace: TraceProtocol
    failure_policy: FailurePolicy
    validity_rules: list[ValidityRule]
    unsafe_mode: bool
    extensions: dict[str, Any] = Field(default_factory=dict)


class DraftConfiguration(StrictModel):
    kind: Literal["none", "embedded_heads", "external_checkpoint", "unknown"]
    checkpoint: CheckpointIdentity | None
    variant: str | None
    num_speculative_tokens: int | None = Field(ge=1)
    num_speculative_steps: int | None = Field(ge=1)
    top_k: int | None = Field(ge=1)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_none(self) -> "DraftConfiguration":
        if self.kind == "none" and any(
            value is not None
            for value in (
                self.checkpoint,
                self.num_speculative_tokens,
                self.num_speculative_steps,
                self.top_k,
            )
        ):
            raise ValueError("draft kind 'none' cannot carry draft controls")
        return self


class CurveSelection(StrictModel):
    curve_id: str = Field(min_length=1)
    curve_digest: Digest
    source: SourcePointer
    model_key: str = Field(min_length=1)
    thinking_state: Literal["enabled", "disabled"]
    method: Literal["mtp", "eagle", "eagle3", "draft_model", "dspark", "other"]
    variant: str | None
    num_speculative_tokens: int = Field(ge=1)
    acceptance_length: float = Field(ge=1)
    statistic: Literal["mean_acceptance_length"]
    rounding_decimals: int = Field(ge=0)


class AcceptanceInjection(StrictModel):
    role: Literal["aggregated", "prefill", "decode"]
    framework: str = Field(min_length=1)
    surface: Literal["environment", "cli_argument", "config_field"]
    location: str = Field(min_length=1)
    transform: Literal["identity", "minus_one", "acceptance_rate", "position_schedule", "other"]
    encoded_value: Any
    evaluation_scope: Literal["throughput", "accuracy", "all"]
    native_value: Any


class RuntimeVerification(StrictModel):
    status: Literal["verified", "failed", "not_verified", "unknown"]
    observed_acceptance_length: float | None = Field(ge=0)
    tolerance: float | None = Field(ge=0)
    evidence: list[ArtifactPointer]


class AcceptanceContract(StrictModel):
    mode: Literal["synthetic_golden", "real", "disabled", "unknown"]
    curve_selection: CurveSelection | None
    injections: list[AcceptanceInjection]
    runtime_verification: RuntimeVerification

    @model_validator(mode="after")
    def validate_mode(self) -> "AcceptanceContract":
        if self.mode == "synthetic_golden":
            if self.curve_selection is None or not self.injections:
                raise ValueError("synthetic_golden requires a curve cell and injections")
            if any(item.evaluation_scope != "throughput" for item in self.injections):
                raise ValueError("synthetic_golden injections are throughput-only")
        elif self.mode == "real":
            if self.curve_selection is not None:
                raise ValueError("real acceptance cannot select a synthetic curve")
            if any(item.evaluation_scope not in {"accuracy", "all"} for item in self.injections):
                raise ValueError("real-acceptance restoration applies only to accuracy/all scope")
        elif self.mode == "disabled":
            if self.curve_selection is not None or self.injections:
                raise ValueError("disabled acceptance cannot carry policy injections")
        return self


class RoleSpeculativeConfiguration(StrictModel):
    role: Literal["aggregated", "prefill", "decode"]
    enabled: bool
    method: SpeculativeMethod
    draft: DraftConfiguration
    acceptance: AcceptanceContract
    effective_server_config_digest: Digest | None = None

    @model_validator(mode="after")
    def validate_disabled(self) -> "RoleSpeculativeConfiguration":
        if not self.enabled and (
            self.method != "none"
            or self.draft.kind != "none"
            or self.acceptance.mode != "disabled"
        ):
            raise ValueError("disabled roles must use none/none/disabled semantics")
        return self


class SpeculativeDecodingContract(StrictModel):
    declared_method: SpeculativeMethod
    roles: list[RoleSpeculativeConfiguration] = Field(min_length=1)
    consistency_status: Literal["consistent", "inconsistent", "unknown"]

    @model_validator(mode="after")
    def validate_roles(self) -> "SpeculativeDecodingContract":
        roles = [role.role for role in self.roles]
        if len(roles) != len(set(roles)):
            raise ValueError("speculative role names must be unique")
        enabled_methods = {role.method for role in self.roles if role.enabled}
        if self.consistency_status == "consistent":
            if self.declared_method == "none" and enabled_methods:
                raise ValueError("declared none conflicts with enabled roles")
            if self.declared_method != "none" and enabled_methods != {self.declared_method}:
                raise ValueError("enabled roles conflict with declared speculative method")
            for role in self.roles:
                selection = role.acceptance.curve_selection
                if selection is None:
                    continue
                if selection.method != role.method:
                    raise ValueError("curve method must equal the effective role method")
                if selection.num_speculative_tokens != role.draft.num_speculative_tokens:
                    raise ValueError("curve K must equal the effective role draft K")
                if selection.acceptance_length > selection.num_speculative_tokens + 1:
                    raise ValueError("selected acceptance length cannot exceed K + 1")
                if any(injection.role != role.role for injection in role.acceptance.injections):
                    raise ValueError("acceptance injections must name their containing role")
        return self


class BehaviorSource(StrictModel):
    inferencex_commit: GitObjectId
    sources: list[SourcePointer] = Field(min_length=1)
    resolution_warnings: list[str]


class BehaviorContract(StrictModel):
    behavior_schema_version: Literal["inferencex.behavior/v1"]
    contract_id: str | None
    contract_digest: Digest | None
    contract_digest_scope: Literal[
        "planned_behavior_excluding_contract_identity_and_runtime_verification"
    ]
    status: Literal["resolved", "partial", "unknown"]
    benchmark_protocol: BenchmarkProtocol | None
    request: RequestContract | None
    speculative_decoding: SpeculativeDecodingContract | None
    source: BehaviorSource | None
    extensions: dict[str, Any]

    @model_validator(mode="after")
    def validate_status(self) -> "BehaviorContract":
        if self.status == "resolved":
            if any(
                value is None
                for value in (
                    self.contract_id,
                    self.contract_digest,
                    self.benchmark_protocol,
                    self.request,
                    self.speculative_decoding,
                    self.source,
                )
            ):
                raise ValueError("resolved behavior contracts require every identity section")
            assert self.request is not None
            assert self.speculative_decoding is not None
            if self.request.thinking.state == "unknown":
                raise ValueError("resolved behavior cannot have unknown thinking state")
            if self.request.chat_template.status != "resolved":
                raise ValueError("resolved behavior requires resolved chat-template identity")
            if self.speculative_decoding.consistency_status != "consistent":
                raise ValueError("resolved behavior requires consistent speculative roles")
            for role in self.speculative_decoding.roles:
                selection = role.acceptance.curve_selection
                if selection is not None and selection.thinking_state != self.request.thinking.state:
                    raise ValueError("curve thinking state must equal resolved request thinking state")
        return self


class BehaviorContractDocument(StrictModel):
    document_type: Literal["inferencex.behavior-contract"]
    schema_version: Literal["inferencex.behavior/v1"]
    generated_at: str
    behavior: BehaviorContract

    @model_validator(mode="after")
    def validate_generated_at(self) -> "BehaviorContractDocument":
        datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        return self


class GoldenDistribution(StrictModel):
    kind: Literal[
        "mean_only", "empirical_pmf", "minimum_variance_pmf", "position_probabilities"
    ]
    values: list[float]
    derivation: str | None


class GoldenPoint(StrictModel):
    num_speculative_tokens: int = Field(ge=1)
    acceptance_length: float = Field(ge=1)
    distribution: GoldenDistribution

    @model_validator(mode="after")
    def validate_acceptance_range(self) -> "GoldenPoint":
        if self.acceptance_length > self.num_speculative_tokens + 1:
            raise ValueError("acceptance_length cannot exceed K + 1")
        if self.distribution.kind == "mean_only" and self.distribution.values:
            raise ValueError("mean_only distributions must not invent probability values")
        if self.distribution.kind != "mean_only" and self.distribution.derivation is None:
            raise ValueError("derived/empirical distributions require a derivation")
        if self.distribution.kind in {"empirical_pmf", "minimum_variance_pmf"}:
            if len(self.distribution.values) != self.num_speculative_tokens + 1:
                raise ValueError("acceptance-length PMF must contain K + 1 probabilities")
            if abs(sum(self.distribution.values) - 1.0) > 1e-9:
                raise ValueError("acceptance-length PMF probabilities must sum to 1")
        if self.distribution.kind == "position_probabilities":
            if len(self.distribution.values) != self.num_speculative_tokens:
                raise ValueError("position probability schedule must contain K values")
            if any(
                left < right
                for left, right in zip(
                    self.distribution.values, self.distribution.values[1:]
                )
            ):
                raise ValueError("position acceptance probabilities must be non-increasing")
        return self


class GoldenMode(StrictModel):
    thinking_state: Literal["enabled", "disabled"]
    sampling: SamplingParameters
    chat_template: ChatTemplateContract
    points: list[GoldenPoint] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_points(self) -> "GoldenMode":
        levels = [point.num_speculative_tokens for point in self.points]
        if len(levels) != len(set(levels)):
            raise ValueError("golden curve K values must be unique within a thinking mode")
        return self


class GoldenDataset(StrictModel):
    repository: str = Field(min_length=1)
    revision: str | None
    resolved_commit: str | None
    split: str = Field(min_length=1)
    digest: Digest | None


class GoldenImage(StrictModel):
    reference: str = Field(min_length=1)
    manifest_digest: Digest | None


class GoldenCollection(StrictModel):
    dataset: GoldenDataset
    category: str = Field(min_length=1)
    prompt_count: int = Field(ge=1)
    output_length: int = Field(ge=1)
    formula: Literal["1 + accepted_draft_tokens / verification_steps"]
    statistic: Literal["mean_acceptance_length"]
    rounding_decimals: int = Field(ge=0)
    framework: str = Field(min_length=1)
    framework_version: str | None
    image: GoldenImage
    hardware: str = Field(min_length=1)
    collector: SourcePointer
    workflow_run_url: str
    workflow_run_id: int = Field(ge=1)
    workflow_run_attempt: int = Field(ge=1)
    artifacts: list[ArtifactPointer]


class GoldenValidation(StrictModel):
    review_status: Literal["pending", "approved", "rejected"]
    reviewed_by: list[str]
    reviewed_at: str | None
    notes: list[str]

    @model_validator(mode="after")
    def validate_reviewed_at(self) -> "GoldenValidation":
        if self.reviewed_at is not None:
            datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
        return self


class GoldenAcceptanceCurve(StrictModel):
    curve_schema_version: Literal["inferencex.golden-acceptance/v1"]
    curve_id: str = Field(min_length=1)
    curve_digest: Digest
    status: Literal["draft", "active", "deprecated"]
    model_key: str = Field(min_length=1)
    target_checkpoint: CheckpointIdentity
    draft: DraftConfiguration
    method: Literal["mtp", "eagle", "eagle3", "draft_model", "dspark", "other"]
    variant: str | None
    modes: list[GoldenMode] = Field(min_length=1)
    collection: GoldenCollection
    source: SourcePointer
    validation: GoldenValidation

    @model_validator(mode="after")
    def validate_curve(self) -> "GoldenAcceptanceCurve":
        modes = [mode.thinking_state for mode in self.modes]
        if len(modes) != len(set(modes)):
            raise ValueError("thinking modes must be unique within a golden curve")
        if self.status == "active":
            if self.validation.review_status != "approved":
                raise ValueError("active curves must be approved")
            required_provenance = (
                self.target_checkpoint.revision,
                self.target_checkpoint.resolved_commit,
                self.target_checkpoint.digest,
                self.collection.dataset.revision,
                self.collection.dataset.resolved_commit,
                self.collection.dataset.digest,
                self.collection.framework_version,
                self.collection.image.manifest_digest,
                self.validation.reviewed_at,
            )
            if any(value is None for value in required_provenance):
                raise ValueError("active curves require complete immutable provenance")
            if any(artifact.digest is None for artifact in self.collection.artifacts):
                raise ValueError("active curves require digests for every retained artifact")
            if not self.collection.artifacts:
                raise ValueError("active curves require retained artifacts")
            if self.draft.kind == "external_checkpoint":
                if self.draft.checkpoint is None or any(
                    value is None
                    for value in (
                        self.draft.checkpoint.revision,
                        self.draft.checkpoint.resolved_commit,
                        self.draft.checkpoint.digest,
                    )
                ):
                    raise ValueError("active external-draft curves require complete draft identity")
        return self


class GoldenAcceptanceCurveDocument(StrictModel):
    document_type: Literal["inferencex.golden-acceptance-curve"]
    schema_version: Literal["inferencex.golden-acceptance/v1"]
    generated_at: str
    curve: GoldenAcceptanceCurve

    @model_validator(mode="after")
    def validate_generated_at(self) -> "GoldenAcceptanceCurveDocument":
        datetime.fromisoformat(self.generated_at.replace("Z", "+00:00"))
        return self


SemanticsDocument: TypeAlias = BehaviorContractDocument | GoldenAcceptanceCurveDocument

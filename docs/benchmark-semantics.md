# AgentX behavior and golden-acceptance contracts

<div align="center">

**English** | [中文](./benchmark-semantics_zh.md)

</div>

InferenceX exposes AgentX request behavior and golden acceptance-length policy as versioned, strict data. Consumers should load these documents instead of reconstructing semantics from launcher text, filenames, comments, or GitHub Actions logs.

The wire-format authority is [`schemas/inferencex-benchmark-semantics-v1.json`](../schemas/inferencex-benchmark-semantics-v1.json). The strict loader and cross-field validator are in [`infx/semantics`](../infx/semantics), and [`utils/benchmark_semantics.py`](../utils/benchmark_semantics.py) is the supported command-line entry point. Both document types reject unknown fields.

## Documents and stability

| `document_type` | Payload | Purpose |
| --- | --- | --- |
| `inferencex.behavior-contract` | `behavior` | The effective AgentX benchmark, request, trace, routing, token-counting, and per-role speculative-decoding plan |
| `inferencex.golden-acceptance-curve` | `curve` | A reviewed, provenance-bearing collection of golden acceptance-length cells |

Both are v1 contracts. A consumer may depend on named fields and enum values within v1, but must reject an unsupported `schema_version`. Nullable or `unknown` fields mean the fact was not established; they do not select an implicit default.

Every document has `generated_at`. A behavior contract carries `contract_id` and `contract_digest`; a curve carries `curve_id` and `curve_digest`. Digests use RFC 8785 JSON canonicalization and SHA-256. `curve_digest` covers the entire `curve` except itself. `contract_digest` covers planned behavior except `contract_id`, `contract_digest`, and `runtime_verification`. The literal `contract_digest_scope` records that projection. Runtime observations can therefore be attached without changing the identity of the plan they verify.

## Behavior contract

A `resolved` behavior contract is the complete pre-run description that makes two AgentX results behaviorally comparable. Its required sections are:

- `benchmark_protocol`: profile and benchmark IDs, canonical/fast/diagnostic mode, exact client implementation, duration, warmup, trace corpus and revision, timing and cache-bust behavior, failure policy, and validity rules.
- `request`: API and endpoint, streaming, served model field, complete `extra_body`, resolved thinking state and its client/server encodings, chat-template identity and kwargs, sampling, headers, conversation affinity, tool choice, response parsing, and tokenizer identity/counting rules.
- `speculative_decoding`: the declared method and one unique effective role entry for `aggregated`, `prefill`, or `decode`. Each role records its draft identity, selected acceptance mode, all concrete injections, and an effective server-config digest when available.
- `source`: the InferenceX commit and immutable source pointers used to resolve the behavior, plus explicit warnings.

For `status=resolved`, thinking may not be `unknown`, the chat-template identity must be resolved, and speculative roles must be consistent. The validator also enforces relationships that ordinary JSON Schema cannot express conveniently: selected curve method and draft length must match the containing role, selected thinking must match request thinking, injection roles must match their containers, and acceptance length must be within `[1, K + 1]`.

`status=partial` is an honest compatibility receipt. It has a digest, but nullable sections and `extensions.missing_fields` show what could not be established. Partial contracts are useful for diagnosis and historical ingestion; they must not be treated as proof that two runs used the same behavior.

### Thinking and chat templates

Thinking is represented as a resolved state plus separate client and server encodings. This prevents values such as `thinking=true`, `enable_thinking=false`, or an engine default from being collapsed into one guessed boolean. Contradictory recognized encodings fail validation.

A resolved chat-template contract states whether templating is used, where tokenization occurs, which tokenizer default/file/inline template is selected, the content digest where applicable, kwargs on both sides, and `add_generation_prompt`. A resolved contract cannot carry `template.kind=unknown`.

### Synthetic versus real acceptance

`synthetic_golden` requires one exact curve cell and at least one throughput-only injection. Accuracy materialization removes that synthetic selection and records the concrete restoration operations as `mode=real`, with `evaluation_scope=accuracy`. `disabled` permits neither a curve nor injections.

The helper emits the canonical framework transforms:

| Framework | Surface | Encoding |
| --- | --- | --- |
| vLLM | `/speculative_config/rejection_sample_method` and `/speculative_config/synthetic_acceptance_length` | Select synthetic rejection and pass AL unchanged |
| SGLang | `SGLANG_SIMULATE_ACC_LEN`, `SGLANG_SIMULATE_ACC_METHOD`, `SGLANG_SIMULATE_ACC_TOKEN_MODE` | Pass AL unchanged, `match-expected`, and `real-draft-token` |
| TensorRT-LLM | `TLLM_SPEC_DECODE_FORCE_NUM_ACCEPTED_TOKENS` | Pass `AL - 1` because the variable excludes the verification token |
| ATOM | `--spec-decode-acceptance-length` | Pass AL unchanged |

Every injection includes its topology role, framework, surface, exact location, transform, encoded value, measurement scope, and native value. The native value makes removal/restoration explicit rather than relying on a presumed engine default.

## Golden acceptance curves

Curve selection is exact. Callers provide `curve_id`, `model_key`, thinking state, speculative method, variant, and `num_speculative_tokens`; the resolver does not normalize aliases or infer identity from a filename. It fails on zero or multiple matches. Draft curves require an explicit `--allow-draft`; normal comparable runs should resolve only `active` curves.

Each curve records:

- stable model, target checkpoint, draft checkpoint/head kind, method, and variant identity;
- separate thinking modes, each with its exact sampling and chat-template behavior;
- one unique point per draft length, with mean AL and an explicit distribution representation;
- dataset, split, immutable revision/digest, category, prompt count, output length, formula, statistic, rounding, framework/image/hardware, collector source, workflow run, and retained artifacts;
- review status, reviewers, review time, and notes.

Distribution `kind=mean_only` intentionally has no invented probabilities. PMFs require `K + 1` probabilities summing to one; position-probability schedules require `K` non-increasing probabilities. Derived and empirical distributions require a derivation statement.

An `active` curve must be approved and carry complete immutable target, dataset, framework, image, artifact, and review provenance. External draft checkpoints must also be immutable. The v1 companions in [`golden_al_distribution/v1`](../golden_al_distribution/v1) preserve every numeric cell from the legacy YAML files, but remain `draft`/`pending` because unavailable historical revisions and artifact digests must not be invented. The legacy YAML remains the current runtime authority until a curve is reviewed and activated.

## Commands

Run the CLI with its explicit lightweight dependencies:

```bash
SEMANTICS_RUN=(uv run --no-project --python 3.12 \
  --with 'pydantic>=2' --with 'PyYAML>=6' --with 'rfc8785>=0.1.4')

"${SEMANTICS_RUN[@]}" utils/benchmark_semantics.py validate \
  golden_al_distribution/v1/*.json

"${SEMANTICS_RUN[@]}" utils/benchmark_semantics.py resolve-curve \
  --curve-id qwen3-5-397b-a17b-nvfp4.mtp.native.speedbench-coding.v1 \
  --model-key qwen3.5-397b-a17b-nvfp4 \
  --thinking-state enabled --method mtp --variant native \
  --num-speculative-tokens 3 --allow-draft

"${SEMANTICS_RUN[@]}" utils/benchmark_semantics.py injections \
  --framework tensorrt-llm --role decode \
  --acceptance-length 3.5 --num-speculative-tokens 4
```

Use `stamp INPUT --output OUTPUT` after authoring a YAML or JSON document with placeholder identity fields; it computes and validates the digest and deterministic behavior ID. Use `materialize CONTRACT --measurement throughput|accuracy --output OUTPUT` to produce the exact measurement-specific contract. Re-running [`utils/migrate_golden_curves.py`](../utils/migrate_golden_curves.py) deterministically regenerates the historical v1 companions from its explicit metadata table and the legacy numeric cells.

## Runtime emission and consumer rules

The AgentX runner stages `results/behavior_contract.json` before replay and validates it before aggregation. If `INFERENCEX_BEHAVIOR_CONTRACT` names a producer-authored resolved contract, the runner materializes the requested measurement semantics. Otherwise it emits a partial legacy snapshot containing centrally observable runtime values and a digest of `benchmark_command.txt`; the command text itself is not embedded so credentials and internal endpoints cannot leak.

`process_agentic_result.py` validates the staged document and embeds its `behavior` object plus `behavior_contract_digest` in the aggregate JSON. Direct processing of older result directories without a staged receipt remains supported and simply omits those fields.

Consumers should:

1. Validate the whole document and its digest with the strict loader.
2. Require `status=resolved` before using a digest as a comparability key.
3. Compare `contract_digest` for planned behavior and inspect `runtime_verification` separately.
4. Treat `not_verified` as no runtime claim, never as a successful check.
5. Resolve curves only by their explicit semantic identity and verify the selected `curve_digest`.

The current workflow/config matrix does not yet expose a first-class behavior-contract field. Until it does, ordinary checked-in recipes emit partial receipts unless their launch environment explicitly sets `INFERENCEX_BEHAVIOR_CONTRACT`. This limitation is visible in the artifact rather than hidden behind inferred defaults.

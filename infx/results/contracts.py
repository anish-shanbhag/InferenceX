"""Versioned, self-describing benchmark result and manifest helpers.

The exchange schema is the public contract.  This module deliberately uses only
the Python standard library so result processing keeps working in benchmark
images that do not ship InferenceX's control-plane dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, TypedDict

EXCHANGE_SCHEMA_VERSION = "inferencex.exchange/v1"
RESULT_SCHEMA_VERSION = "inferencex.result/v1"
CANONICALIZATION = "RFC8785"

_SECRET_NAME = re.compile(
    r"(?:^|_)(?:AUTH|COOKIE|CREDENTIAL|KEY|PASSWORD|SECRET|TOKEN)(?:_|$)", re.I
)
_SPEC_METHODS = {"none", "mtp", "eagle", "eagle3", "draft_model", "dspark"}
_CREDENTIAL_URL = re.compile(r"(?i)^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@")
_BEARER_VALUE = re.compile(r"(?i)^bearer\s+\S+$")


class CollectionInput(TypedDict, total=False):
    path: str
    digest: str
    kind: str
    status: Literal["valid", "invalid", "legacy", "unreadable"]
    errors: list[str]


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp without platform-specific formatting."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON values using RFC 8785 (JCS) ordering and number rules."""
    def number(item: float) -> str:
        if not math.isfinite(item):
            raise ValueError("Canonical JSON cannot contain a non-finite number")
        if item == 0:
            return "0"
        absolute = abs(item)
        if 1e-6 <= absolute < 1e21:
            rendered = format(Decimal(repr(item)), "f")
            return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered
        coefficient, exponent = repr(item).lower().split("e")
        coefficient = coefficient.rstrip("0").rstrip(".")
        exponent_number = int(exponent)
        sign = "+" if exponent_number >= 0 else ""
        return f"{coefficient}e{sign}{exponent_number}"

    def render(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            if abs(item) > 9_007_199_254_740_991:
                raise ValueError("RFC 8785 integers must be exactly representable as IEEE-754")
            return str(item)
        if isinstance(item, float):
            return number(item)
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise TypeError("Canonical JSON object keys must be strings")
            keys = sorted(item, key=lambda key: key.encode("utf-16be", "surrogatepass"))
            return "{" + ",".join(f"{render(key)}:{render(item[key])}" for key in keys) + "}"
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            return "[" + ",".join(render(child) for child in item) + "]"
        raise TypeError(f"Not a JSON value: {type(item).__name__}")

    return render(value).encode("utf-8")


def digest_json(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _hex_digest(value: str) -> str | None:
    value = value.removeprefix("sha256:")
    return f"sha256:{value}" if re.fullmatch(r"[0-9a-f]{64}", value) else None


def _bool(value: Any) -> bool:
    return value is True or str(value).lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _positive(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo_root, check=True, capture_output=True, text=True
        ).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_blob(repo_root: Path, commit: str | None, path: str) -> str | None:
    if not commit:
        return None
    return _git(repo_root, "rev-parse", f"{commit}:{path}")


def redact_sensitive(value: Any, pointer: str = "") -> tuple[Any, list[str]]:
    """Recursively redact secret-like keys, argv values, and credential URLs."""
    locations: list[str] = []
    if isinstance(value, Mapping):
        clean: dict[str, Any] = {}
        for key, child in value.items():
            child_pointer = f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if _SECRET_NAME.search(str(key)):
                clean[str(key)] = "[REDACTED]"
                locations.append(child_pointer)
            else:
                clean[str(key)], nested = redact_sensitive(child, child_pointer)
                locations.extend(nested)
        return clean, locations
    if isinstance(value, list):
        clean_list: list[Any] = []
        redact_next = False
        for index, child in enumerate(value):
            child_pointer = f"{pointer}/{index}"
            if redact_next:
                clean_list.append("[REDACTED]")
                locations.append(child_pointer)
                redact_next = False
                continue
            if isinstance(child, str) and child.startswith("--"):
                flag, separator, _ = child.partition("=")
                if _SECRET_NAME.search(flag.replace("-", "_")):
                    clean_list.append(f"{flag}=[REDACTED]" if separator else child)
                    locations.append(child_pointer + ("/value" if separator else ""))
                    redact_next = not separator
                    continue
            cleaned, nested = redact_sensitive(child, child_pointer)
            clean_list.append(cleaned)
            locations.extend(nested)
        return clean_list, locations
    if isinstance(value, str) and (_CREDENTIAL_URL.search(value) or _BEARER_VALUE.search(value)):
        return "[REDACTED]", [pointer or "/"]
    return value, locations


def redact_environment(
    environment: Mapping[str, Any], *, explicitly_redacted: Sequence[str] = ()
) -> tuple[dict[str, str | None], list[str]]:
    """Return a deterministic non-secret environment receipt.

    Names remain visible when values are omitted, which distinguishes a secret
    from an absent semantic input.  Non-scalar values are rejected instead of
    being stringified ambiguously.
    """
    forced = set(explicitly_redacted)
    clean: dict[str, str | None] = {}
    redacted: list[str] = []
    for name in sorted(environment):
        if name in forced or _SECRET_NAME.search(name):
            redacted.append(name)
            continue
        value = environment[name]
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise TypeError(f"Environment value for {name} must be scalar or null")
        clean[name] = None if value is None else str(value)
    return clean, redacted


def build_effective_execution(receipt: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalize a launcher-authored execution receipt and redact secrets."""
    if receipt is None:
        return None
    roles: list[dict[str, Any]] = []
    raw_roles = receipt.get("roles")
    if not isinstance(raw_roles, list) or not raw_roles:
        raise ValueError("Execution receipt must contain at least one role")
    for raw in raw_roles:
        if not isinstance(raw, Mapping):
            raise TypeError("Execution roles must be JSON objects")
        argv = raw.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv):
            raise ValueError("Execution role argv must be a nonempty string array")
        environment, redacted = redact_environment(
            raw.get("environment", {}),
            explicitly_redacted=raw.get("redacted_environment_names", []),
        )
        safe_raw, redacted_locations = redact_sensitive(dict(raw), f"/roles/{len(roles)}")
        resolved_config = safe_raw.get("resolved_config")
        role = {
            "role": safe_raw.get("role", "other"),
            "component": safe_raw.get("component") or {"name": "unknown", "version": None},
            "container_role": safe_raw.get("container_role", str(safe_raw.get("role", "other"))),
            "argv": safe_raw["argv"],
            "environment": environment,
            "redacted_environment_names": sorted(set(redacted)),
            "working_directory": safe_raw.get("working_directory"),
            "mounts": safe_raw.get("mounts", []),
            "resolved_config": resolved_config,
            "resolved_config_digest": (
                digest_json(resolved_config) if isinstance(resolved_config, Mapping) else None
            ),
            "extensions": {
                **dict(safe_raw.get("extensions", {})),
                "redacted_locations": sorted(set(redacted_locations)),
            },
        }
        roles.append(role)
    normalized = {
        "schema_version": "inferencex.execution/v1",
        "format": receipt.get("format", "multi_role"),
        "digest": "",
        "roles": roles,
        "redaction_policy": receipt.get(
            "redaction_policy", "inferencex-secret-name-v1"
        ),
    }
    normalized["digest"] = digest_json({k: v for k, v in normalized.items() if k != "digest"})
    return normalized


def load_execution_receipt(env: Mapping[str, str]) -> dict[str, Any] | None:
    raw = env.get("INFERENCEX_EXECUTION_RECEIPT")
    path = env.get("INFERENCEX_EXECUTION_RECEIPT_PATH")
    if raw and path:
        raise ValueError("Set only one execution receipt source")
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    if not raw:
        return None
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("Execution receipt must be a JSON object")
    return build_effective_execution(value)


def matrix_fingerprint(matrix: Mapping[str, Any]) -> str:
    identity = {
        key: value
        for key, value in matrix.items()
        if key not in {"conc", "exp-name", "recipe-fingerprint", "queue-token", "priority"}
    }
    return digest_json(identity)


def build_plan(matrix: Mapping[str, Any], *, job_key: str, job_name: str) -> dict[str, Any]:
    """Build a pre-runtime plan identity without claiming final point identity."""
    fingerprint = digest_json(
        {"resolved_matrix_entry": matrix, "job_key": job_key, "job_name": job_name}
    )
    return {
        "plan_id": "infx-plan-" + fingerprint.removeprefix("sha256:"),
        "plan_fingerprint": fingerprint,
        "point_id": None,
        "matrix_fingerprint": matrix_fingerprint(matrix),
        "point_fingerprint": None,
        "resolved_matrix_entry": dict(matrix),
        "job_key": job_key,
        "job_name": job_name,
    }


def source_run(
    repo_root: Path,
    env: Mapping[str, str],
    *,
    status: str = "in_progress",
    conclusion: str | None = None,
    source_run_id: int | None = None,
    source_run_attempt: int | None = None,
    source_head_sha: str | None = None,
    source_url: str | None = None,
    external_source: bool = False,
) -> dict[str, Any]:
    repository = env.get("GITHUB_REPOSITORY", "SemiAnalysisAI/InferenceX")
    run_id = source_run_id or _int(env.get("GITHUB_RUN_ID"), 1)
    attempt = source_run_attempt or _int(env.get("GITHUB_RUN_ATTEMPT"), 1)
    head = source_head_sha or env.get("GITHUB_SHA") or _git(repo_root, "rev-parse", "HEAD") or "0" * 40
    base = env.get("INFERENCEX_BASE_SHA") or None
    reuse_id = _int(env.get("INFERENCEX_REUSE_SOURCE_RUN_ID")) or None
    reuse_attempt = _int(env.get("INFERENCEX_REUSE_SOURCE_RUN_ATTEMPT")) or None
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    return {
        "repository": repository,
        "run_id": run_id,
        "run_attempt": max(1, attempt),
        "job_id": None if external_source else (_int(env.get("INFERENCEX_GITHUB_JOB_ID")) or None),
        "job_name": None if external_source else (env.get("GITHUB_JOB") or None),
        "event": "unknown" if external_source else env.get("GITHUB_EVENT_NAME", "local"),
        "head_sha": head,
        "base_sha": base,
        "status": status,
        "conclusion": conclusion,
        "url": source_url or f"{server}/{repository}/actions/runs/{run_id}/attempts/{max(1, attempt)}",
        "started_at": None if external_source else (env.get("INFERENCEX_JOB_STARTED_AT") or None),
        "completed_at": utc_now() if status == "completed" else None,
        "reuse": {
            "reused": reuse_id is not None,
            "source_run_id": reuse_id,
            "source_run_attempt": reuse_attempt,
            "source_record_id": env.get("INFERENCEX_REUSE_SOURCE_RECORD_ID") or None,
        },
    }


def _find_recipe_path(matrix: Mapping[str, Any]) -> str | None:
    def visit(value: Any) -> str | None:
        if isinstance(value, Mapping):
            for child in value.values():
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, str) and value.startswith("CONFIG_FILE="):
            path = value.split("=", 1)[1]
            if path.startswith("recipes/"):
                return "benchmarks/multi_node/srt-slurm-recipes/" + path.removeprefix("recipes/")
            return path
        return None

    return visit(matrix)


def build_source_lock(
    repo_root: Path, matrix: Mapping[str, Any], env: Mapping[str, str]
) -> dict[str, Any]:
    # The reusable benchmark may checkout ``inputs.ref``; repository HEAD is
    # therefore the measured source, while GITHUB_SHA remains run metadata.
    commit = _git(repo_root, "rev-parse", "HEAD") or env.get("GITHUB_SHA")
    tree = _git(repo_root, "rev-parse", f"{commit}^{{tree}}") if commit else None
    files: list[dict[str, Any]] = []
    candidates = [
        ("matrix_generator", "infx/matrix/generate.py", None),
        ("workflow", ".github/workflows/benchmark-tmpl.yml", None),
        ("workflow", ".github/workflows/benchmark-multinode-tmpl.yml", None),
        ("result_processor", "infx/results/fixed_sequence.py", "fixed_sequence"),
        ("result_processor", "utils/agentic/aggregation/process_agentic_result.py", "agentx"),
    ]
    recipe = _find_recipe_path(matrix)
    if recipe:
        candidates.append(("recipe", recipe, None))
    launcher = f"runners/launch_{str(matrix.get('runner', '')).removeprefix('cluster:').split('-', 1)[0]}.sh"
    if (repo_root / launcher).is_file():
        candidates.append(("runner", launcher, None))
    for kind, path, role in candidates:
        blob = _git_blob(repo_root, commit, path)
        if blob:
            files.append({
                "kind": kind, "repository": env.get("GITHUB_REPOSITORY", "SemiAnalysisAI/InferenceX"),
                "commit": commit, "path": path, "blob_object_id": blob, "role": role,
            })
    image = str(matrix.get("image") or env.get("IMAGE", "unknown"))
    unresolved = [
        "/source_lock/images/0/manifest_digest",
        "/source_lock/model_artifacts/0/resolved_commit",
        "/source_lock/model_artifacts/0/digest",
    ]
    if not commit:
        unresolved.append("/source_lock/inferencex/commit")
    lock = {
        "canonicalization": CANONICALIZATION,
        "source_lock_digest": None,
        "inferencex": {
            "repository": env.get("GITHUB_REPOSITORY", "SemiAnalysisAI/InferenceX"),
            "commit": commit, "tree_object_id": tree,
        },
        "files": sorted(files, key=lambda item: (item["path"], item["kind"])),
        "repository_dependencies": [],
        "images": [{
            "role": "server", "declared_reference": image,
            "platform": env.get("INFERENCEX_IMAGE_PLATFORM") or None,
            "manifest_digest": _hex_digest(env.get("INFERENCEX_IMAGE_DIGEST", "")),
        }],
        "model_artifacts": [{
            "role": "target", "repository": str(matrix.get("model") or env.get("MODEL", "unknown")),
            "revision": env.get("INFERENCEX_MODEL_REVISION") or None,
            "resolved_commit": env.get("INFERENCEX_MODEL_COMMIT") or None,
            "digest": _hex_digest(env.get("INFERENCEX_MODEL_DIGEST", "")),
        }],
        "patches": [], "materializations": [], "unresolved": sorted(set(unresolved)),
    }
    if lock["images"][0]["manifest_digest"]:
        lock["unresolved"].remove("/source_lock/images/0/manifest_digest")
    if lock["model_artifacts"][0]["resolved_commit"]:
        lock["unresolved"].remove("/source_lock/model_artifacts/0/resolved_commit")
    if lock["model_artifacts"][0]["digest"]:
        lock["unresolved"].remove("/source_lock/model_artifacts/0/digest")
    lock["source_lock_digest"] = digest_json({
        "source_lock": {k: v for k, v in lock.items() if k != "source_lock_digest"},
        "resolved_matrix_entry": matrix,
    })
    return lock


def _component(value: Any, fallback: str) -> dict[str, Any]:
    if isinstance(value, Mapping) and value.get("name"):
        return {"name": str(value["name"]), "version": value.get("version")}
    return {"name": fallback, "version": None}


def _worker_role(
    role: str, worker: Mapping[str, Any], physical: int, hardware: str | None
) -> dict[str, Any]:
    count = max(0, _int(worker.get("num-worker"), 1))
    return {
        "role": role, "worker_count": count,
        "accelerators_per_worker": physical // count if count else 0,
        "physical_accelerators": physical,
        "tp": max(0, _int(worker.get("tp"), 0)), "pp": max(1, _int(worker.get("pp"), 1)),
        "dcp": max(1, _int(worker.get("dcp-size"), 1)), "pcp": max(1, _int(worker.get("pcp-size"), 1)),
        "ep": max(0, _int(worker.get("ep"), 0)), "dp_attention": _bool(worker.get("dp-attn")),
        "hardware": hardware, "additional_settings": list(worker.get("additional-settings", [])),
    }


def _roles(row: Mapping[str, Any], matrix: Mapping[str, Any]) -> list[dict[str, Any]]:
    if row.get("is_multinode") or matrix.get("prefill"):
        def role_values(role: str) -> dict[str, Any]:
            nested = matrix.get(role) if isinstance(matrix.get(role), Mapping) else {}
            result = dict(nested)
            aliases = {
                "num-worker": "num_workers", "tp": "tp", "pp": "pp",
                "dcp-size": "dcp_size", "pcp-size": "pcp_size", "ep": "ep",
                "dp-attn": "dp_attention", "hardware": "hw",
            }
            for target, suffix in aliases.items():
                flat = matrix.get(f"{role}-{target}")
                observed = row.get(f"{role}_{suffix}")
                if flat is not None:
                    result[target] = flat
                if observed is not None:
                    result[target] = observed
            return result

        prefill = role_values("prefill")
        decode = role_values("decode")
        p_count = _int(row.get("num_prefill_gpu")) or (
            max(0, _int(prefill.get("num-worker"), 1)) * max(0, _int(prefill.get("tp")))
            * max(1, _int(prefill.get("pp"), 1)) * max(1, _int(prefill.get("pcp-size"), 1))
        )
        d_count = _int(row.get("num_decode_gpu")) or (
            max(0, _int(decode.get("num-worker"))) * max(0, _int(decode.get("tp")))
            * max(1, _int(decode.get("pp"), 1)) * max(1, _int(decode.get("pcp-size"), 1))
        )
        first_role = "prefill" if _bool(row.get("disagg", matrix.get("disagg"))) else "aggregated"
        result = [_worker_role(first_role, prefill, p_count, row.get("prefill_hw") or row.get("hw"))]
        if d_count:
            result.append(_worker_role("decode", decode, d_count, row.get("decode_hw") or row.get("hw")))
        return result
    tp = max(1, _int(row.get("tp", matrix.get("tp")), 1))
    pp = max(1, _int(row.get("pp", matrix.get("pp")), 1))
    pcp = max(1, _int(row.get("pcp_size", matrix.get("pcp-size")), 1))
    worker = {
        "num-worker": 1, "tp": tp, "pp": pp,
        "dcp-size": row.get("dcp_size", matrix.get("dcp-size", 1)),
        "pcp-size": pcp, "ep": row.get("ep", matrix.get("ep", 1)),
        "dp-attn": row.get("dp_attention", matrix.get("dp-attn", False)),
    }
    return [_worker_role("aggregated", worker, tp * pp * pcp, str(row.get("hw", "unknown")))]


def _load_behavior(env: Mapping[str, str]) -> dict[str, Any] | None:
    path = env.get("INFERENCEX_BEHAVIOR_CONTRACT_PATH")
    raw = env.get("INFERENCEX_BEHAVIOR_CONTRACT")
    if path:
        raw = Path(path).read_text(encoding="utf-8")
    if not raw:
        return None
    parsed = json.loads(raw)
    return parsed.get("behavior") if parsed.get("document_type") == "inferencex.behavior-contract" else parsed


def _measurement(row: Mapping[str, Any], agentx: bool) -> dict[str, Any]:
    if agentx:
        request = row.get("request_metrics") if isinstance(row.get("request_metrics"), Mapping) else {}
        throughput = request.get("throughput") if isinstance(request.get("throughput"), Mapping) else {}
        per_gpu = throughput.get("per_gpu") if isinstance(throughput.get("per_gpu"), Mapping) else {}
        latency = request.get("latency") if isinstance(request.get("latency"), Mapping) else {}
        full = latency.get("full_response_intvty") if isinstance(latency.get("full_response_intvty"), Mapping) else {}
        tput = _positive(per_gpu.get("total_tput_tps"))
        intvty = _positive(full.get("p90"))
        statistic = "p90_full_response" if intvty else None
        total = _positive(throughput.get("total_tput_tps"))
        input_tput = _positive(throughput.get("input_tput_tps"))
        output_tput = _positive(throughput.get("output_tput_tps"))
    else:
        tput = _positive(row.get("tput_per_gpu"))
        intvty = _positive(row.get("intvty_p50"))
        statistic = "median_token" if intvty else None
        total = _positive(row.get("total_token_throughput"))
        input_tput = _positive(row.get("input_tput_per_gpu"))
        output_tput = _positive(row.get("output_tput_per_gpu"))
    status = "valid" if tput and intvty else "incomplete"
    return {
        "kind": "throughput", "status": status, "measured_at": None,
        "metrics": {
            "objective_profile_id": "agentx-throughput-p90-full-response-v1" if agentx else "fixed-sequence-median-token-v1",
            "throughput_per_accelerator_tps": tput,
            "interactivity_tps_per_user": intvty,
            "interactivity_statistic": statistic,
            "total_token_throughput_tps": total,
            "input_token_throughput_tps": input_tput,
            "output_token_throughput_tps": output_tput,
            "average_power_watts_per_accelerator": _positive(row.get("avg_power_per_gpu_w")),
            "energy_joules_per_token": _positive(row.get("energy_per_token_j")),
        },
        "raw_metrics": dict(row), "validation": [],
        "warnings": list(row.get("warnings", [])) if isinstance(row.get("warnings"), list) else [],
    }


def build_result_record(
    row: Mapping[str, Any], matrix: Mapping[str, Any], repo_root: Path,
    env: Mapping[str, str], *, result_ordinal: int = 0, result_path: Path | None = None,
) -> dict[str, Any]:
    """Convert a fixed-sequence or AgentX legacy row without changing that row."""
    agentx = row.get("scenario_type") == "agentic-coding" or matrix.get("scenario-type") == "agentic-coding"
    roles = _roles(row, matrix)
    active = sum(role["physical_accelerators"] for role in roles)
    if active <= 0:
        raise ValueError("A result record requires at least one active accelerator")
    concurrency = max(1, _int(row.get("conc", matrix.get("conc")), 1))
    behavior = (
        dict(row["behavior_contract"])
        if agentx and isinstance(row.get("behavior_contract"), Mapping)
        else (_load_behavior(env) if agentx else None)
    )
    declared_behavior_digest = row.get("behavior_contract_digest")
    if declared_behavior_digest and (
        not behavior or behavior.get("contract_digest") != declared_behavior_digest
    ):
        raise ValueError("AgentX behavior_contract_digest does not match embedded contract")
    if agentx:
        dataset = row.get("dataset") if isinstance(row.get("dataset"), Mapping) else None
        dataset_identity = None if dataset is None else {
            "loader": str(dataset.get("loader", "unknown")), "corpus": str(dataset.get("corpus", dataset.get("name", "unknown"))),
            "repository": dataset.get("repository") or dataset.get("name"), "revision": dataset.get("revision"),
            "resolved_commit": dataset.get("resolved_commit"), "split": dataset.get("split"),
            "digest": _hex_digest(str(dataset.get("digest", ""))), "filters": dict(dataset.get("filters", {})),
        }
        workload = {
            "kind": "agentx", "workload_id": str(matrix.get("exp-name", "agentx")), "workload_digest": None,
            "profile_id": (
                behavior["benchmark_protocol"].get("profile_id")
                if behavior and isinstance(behavior.get("benchmark_protocol"), Mapping)
                else None
            ),
            "benchmark_mode": "fast" if _bool(env.get("AIPERF_EXPERIMENTAL_FAST")) else "canonical",
            "duration_seconds": _int(matrix.get("duration", env.get("DURATION"))) or None,
            "dataset": dataset_identity, "behavior_contract": behavior,
        }
    else:
        isl = max(1, _int(row.get("isl", matrix.get("isl")), 1))
        osl = max(1, _int(row.get("osl", matrix.get("osl")), 1))
        workload = {
            "kind": "fixed_sequence", "workload_id": f"fixed-sequence-{isl}-{osl}", "workload_digest": "",
            "input_sequence_length": isl, "output_sequence_length": osl,
            "max_model_length": max(1, _int(matrix.get("max-model-len"), isl + osl)),
            "random_range_ratio": float(matrix.get("random-range-ratio", env.get("RANDOM_RANGE_RATIO", 0.8))),
            "request_generation": {},
        }
        workload["workload_digest"] = digest_json({k: v for k, v in workload.items() if k != "workload_digest"})
    source_lock = build_source_lock(repo_root, matrix, env)
    mf = matrix_fingerprint(matrix)
    point_fingerprint = digest_json({
        "matrix_fingerprint": mf, "source_lock_digest": source_lock["source_lock_digest"],
        "workload": workload, "concurrency": concurrency,
    })
    point_id = "infx-point-" + point_fingerprint.removeprefix("sha256:")
    run = source_run(repo_root, env, status="completed", conclusion="success")
    record_digest = digest_json({
        "point_id": point_id, "run_id": run["run_id"], "run_attempt": run["run_attempt"],
        "job_id": run["job_id"], "job_name": run["job_name"], "result_ordinal": result_ordinal,
    })
    effective = load_execution_receipt(env)
    missing = list(source_lock["unresolved"])
    if agentx and behavior is None:
        missing.append("/workload/behavior_contract")
    if effective is None:
        missing.append("/effective_execution")
    method_raw = str(row.get("spec_decoding", matrix.get("spec-decoding", "none"))).lower()
    method = method_raw if method_raw in _SPEC_METHODS else "other"
    benchmark_type = "agentx" if agentx else "fixed_sequence"
    framework = str(row.get("framework", matrix.get("framework", "unknown")))
    artifacts = []
    if result_path and result_path.is_file():
        artifacts.append({
            "name": result_path.name, "kind": "result", "url": None,
            "digest": digest_file(result_path), "retention_expires_at": None,
        })
    result = {
        "record_schema_version": RESULT_SCHEMA_VERSION,
        "record_id": "infx-record-" + record_digest.removeprefix("sha256:"),
        "result_ordinal": result_ordinal,
        "point_id": point_id,
        "publication": {"status": "draft", "upstream_row_id": None, "published_at": None, "ingested_at": None, "supersedes_record_id": None},
        "identity": {
            "benchmark_type": benchmark_type, "scenario_type": "agentic-coding" if agentx else "fixed-seq-len",
            "model": {
                "model_prefix": str(row.get("infmax_model_prefix", matrix.get("model-prefix", "unknown"))),
                "display_name": str(row.get("model", matrix.get("model", "unknown"))),
                "served_model_name": str(row.get("model", matrix.get("model", "unknown"))),
                "checkpoint": None, "draft_checkpoint": None,
            },
            "hardware": {
                "runner": str(row.get("hw", matrix.get("runner", "unknown"))),
                "accelerator": str(row.get("hw", matrix.get("runner", "unknown"))).removeprefix("cluster:"),
                "architecture": None, "prefill_accelerator": row.get("prefill_hw"), "decode_accelerator": row.get("decode_hw"),
            },
            "precision": str(row.get("precision", matrix.get("precision", "unknown"))),
            "framework": {"matrix_label": framework, "frontend": None, "backend": _component(None, framework)},
            "topology": "disaggregated" if _bool(row.get("disagg", matrix.get("disagg"))) else "aggregated",
            "speculative_method": method, "speculative_method_raw": method_raw, "extensions": {},
        },
        "workload": workload,
        "point": {
            "concurrency": concurrency, "node_count": max(1, _int(matrix.get("node-count"), 1)),
            "active_accelerator_count": active, "roles": roles,
            "client_placement": {"mode": "unknown", "dedicated_node": None, "colocated_role": "unknown"},
            "kv_offload": {
                "mode": str(row.get("kv_offloading", "none")) if str(row.get("kv_offloading", "none")) in {"none", "dram", "disk", "remote"} else "other",
                "backend": _component(row.get("kv_offload_backend"), str(row.get("kv_offloading", "unknown"))) if str(row.get("kv_offloading", "none")) != "none" else None,
                "allocated_cpu_dram_gb": max(0, _int(row.get("allocated_cpu_dram_gb"))),
                "peer_transfer": row.get("kv_p2p_transfer"), "extensions": {},
            },
            "router": _component(row.get("router"), "unknown") if row.get("router") else None, "extensions": {},
        },
        "resolved_recipe": {
            "generator": None, "config_source": None, "recipe_source": None,
            "resolved_matrix_entry": dict(matrix), "matrix_fingerprint": mf, "point_fingerprint": point_fingerprint,
        },
        "effective_execution": effective, "source_lock": source_lock, "source_run": run,
        "measurement": _measurement(row, agentx), "artifacts": artifacts,
        "reproducibility": {
            "status": "partial", "verified": False, "verified_at": utc_now(),
            "missing_fields": sorted(set(missing)), "notes": ["Forward contract emitted from available producer evidence."],
        },
        "extensions": {
            "legacy_format_preserved": True,
            "legacy_recipe_fingerprint": row.get("recipe_fingerprint") or matrix.get("recipe-fingerprint") or None,
        },
    }
    return result


def result_document(result: Mapping[str, Any]) -> dict[str, Any]:
    return {"document_type": "inferencex.result-record", "schema_version": EXCHANGE_SCHEMA_VERSION, "generated_at": utc_now(), "result": dict(result)}


def job_manifest(
    repo_root: Path, matrix: Mapping[str, Any], env: Mapping[str, str], *, phase: str,
    conclusion: str | None = None, result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    plan = build_plan(matrix, job_key=env.get("GITHUB_JOB", "benchmark"), job_name=env.get("INFERENCEX_JOB_NAME", env.get("GITHUB_JOB", "benchmark")))
    if result:
        plan["point_id"] = result["point_id"]
        plan["point_fingerprint"] = result["resolved_recipe"]["point_fingerprint"]
    status_map = {"success": "success", "failure": "failed", "cancelled": "cancelled", "skipped": "skipped"}
    status = "queued" if phase == "planned" else status_map.get(conclusion or "failure", "failed")
    outcome = {
        "plan_id": plan["plan_id"],
        "point_id": result["point_id"] if result else None,
        "status": status, "job_id": None,
        "record_id": result.get("record_id") if result else None,
        "result_ordinal": result.get("result_ordinal") if result else None,
        "result_artifact": None,
        "job_manifest_artifact": f"inferencex-job-manifest-{plan['plan_id']}",
        "failure": None if status in {"queued", "success"} else {"code": "benchmark_job_failed", "message": f"Job concluded with {conclusion}", "step": None},
    }
    return {
        "document_type": "inferencex.job-manifest", "schema_version": EXCHANGE_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "run": source_run(repo_root, env, status="in_progress" if phase == "planned" else "completed", conclusion=None if phase == "planned" else conclusion),
        "plan": plan, "outcome": outcome, "source_lock": build_source_lock(repo_root, matrix, env),
    }


def iter_matrix_points(matrix_document: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    points: list[tuple[str, dict[str, Any]]] = []
    def visit(value: Any, pointer: str) -> None:
        if isinstance(value, Mapping):
            if value.get("exp-name") and value.get("runner"):
                conc = value.get("conc")
                if conc is None:
                    conc = value.get("conc-list")
                values = conc if isinstance(conc, list) else [conc]
                for ordinal, item in enumerate(values):
                    point = dict(value)
                    point["conc"] = item
                    points.append((f"{pointer}/conc/{ordinal}", point))
            else:
                for key in sorted(value):
                    visit(value[key], f"{pointer}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{pointer}/{index}")
    visit(matrix_document, "")
    return points


def run_manifest(repo_root: Path, matrix_document: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    planned = [build_plan(point, job_key=pointer, job_name=str(point.get("exp-name"))) for pointer, point in iter_matrix_points(matrix_document)]
    commit = env.get("GITHUB_SHA") or _git(repo_root, "rev-parse", "HEAD") or "0" * 40
    generator_path = "infx/matrix/generate.py"
    configs = []
    for path in ("configs/nvidia-master.yaml", "configs/amd-master.yaml"):
        blob = _git_blob(repo_root, commit, path)
        if blob:
            configs.append({"path": path, "blob_object_id": blob})
    generator_blob = _git_blob(repo_root, commit, generator_path) or commit
    current = source_run(repo_root, env)
    reuse_id = _int(env.get("INFERENCEX_REUSE_SOURCE_RUN_ID")) or None
    source = source_run(
        repo_root, env, status="completed", conclusion="success",
        source_run_id=reuse_id,
        source_run_attempt=_int(env.get("INFERENCEX_REUSE_SOURCE_RUN_ATTEMPT")) or None,
        source_head_sha=env.get("INFERENCEX_REUSE_SOURCE_HEAD_SHA") or None,
        source_url=env.get("INFERENCEX_REUSE_SOURCE_RUN_URL") or None,
        external_source=True,
    ) if reuse_id else current
    outcomes = [{
        "plan_id": item["plan_id"], "point_id": None,
        "status": "unknown", "job_id": None, "record_id": None,
        "result_ordinal": None, "result_artifact": None,
        "job_manifest_artifact": f"inferencex-job-manifest-{item['plan_id']}", "failure": None,
    } for item in planned]
    return {
        "document_type": "inferencex.run-manifest", "schema_version": EXCHANGE_SCHEMA_VERSION,
        "generated_at": utc_now(), "source_run": source, "merge_run": current,
        "generation": {
            "generator": {"path": generator_path, "blob_object_id": generator_blob, "schema_version": "inferencex.matrix/v1", "arguments": []},
            "config_sources": configs or [{"path": "unknown", "blob_object_id": commit}],
            "expanded_matrix_digest": digest_json(matrix_document), "filters": {},
        },
        "planned_points": planned, "outcomes": outcomes,
    }

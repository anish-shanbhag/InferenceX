#!/usr/bin/env python3
"""Write versioned InferenceX result records and immutable manifest phases."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from infx.results.contracts import (  # noqa: E402
    build_result_record,
    digest_json,
    iter_matrix_points,
    job_manifest,
    result_document,
    run_manifest,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_object(raw: str | None, path: Path | None) -> dict:
    if bool(raw) == bool(path):
        raise SystemExit("Exactly one of --matrix-json and --matrix-file is required")
    value = json.loads(raw) if raw else json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit("Matrix input must be a JSON object")
    return value


def validate_if_requested(paths: list[Path], schema_dir: Path | None) -> None:
    if schema_dir is None:
        return
    from infx.results.contract_models import validate_exchange_document

    for path in paths:
        validate_exchange_document(json.loads(path.read_text(encoding="utf-8")), schema_dir)


def job_command(args: argparse.Namespace) -> int:
    matrix = load_object(args.matrix_json, args.matrix_file)
    repo_root = args.repo_root.resolve()
    output_dir = args.output_dir.resolve()
    result_documents: list[Path] = []
    manifests: list[dict] = []
    for ordinal, path in enumerate(args.result):
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict) or row.get("document_type"):
            raise SystemExit(f"Legacy result must be a JSON object: {path}")
        point_matrix = dict(matrix)
        point_matrix["conc"] = row.get("conc", point_matrix.get("conc"))
        result = build_result_record(
            row, point_matrix, repo_root, os.environ,
            result_ordinal=ordinal, result_path=path,
        )
        document = result_document(result)
        output = output_dir / f"inferencex-result-record-{ordinal}.json"
        write_json(output, document)
        result_documents.append(output)
        manifests.append(job_manifest(
            repo_root, point_matrix, os.environ, phase=args.phase,
            conclusion=args.conclusion, result=result,
        ))
    if not manifests:
        planned = iter_matrix_points({"points": [matrix]}) or [("/points/0", matrix)]
        manifests = [
            job_manifest(repo_root, point, os.environ, phase=args.phase, conclusion=args.conclusion)
            for _, point in planned
        ]
    group = digest_json([item["plan"]["plan_id"] for item in manifests]).removeprefix("sha256:")
    artifact_name = f"inferencex-{args.phase}-manifests-{group}"
    manifest_paths: list[Path] = []
    for ordinal, manifest in enumerate(manifests):
        manifest["outcome"]["job_manifest_artifact"] = artifact_name
        path = output_dir / f"inferencex-job-manifest-{args.phase}-{ordinal}.json"
        write_json(path, manifest)
        manifest_paths.append(path)
    if args.github_env:
        with args.github_env.open("a", encoding="utf-8") as stream:
            stream.write(f"INFERENCEX_MANIFEST_GROUP_ID={group}\n")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as stream:
            stream.write(f"group-id={group}\n")
    validate_if_requested([*manifest_paths, *result_documents], args.schema_dir)
    print(group)
    return 0


def run_command(args: argparse.Namespace) -> int:
    matrix = load_object(args.matrix_json, args.matrix_file)
    document = run_manifest(args.repo_root.resolve(), matrix, os.environ)
    write_json(args.output, document)
    validate_if_requested([args.output], args.schema_dir)
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    job = subparsers.add_parser("job")
    job.add_argument("--phase", choices=("planned", "final"), required=True)
    job.add_argument("--conclusion", choices=("success", "failure", "cancelled", "skipped"))
    job.add_argument("--matrix-json")
    job.add_argument("--matrix-file", type=Path)
    job.add_argument("--result", type=Path, action="append", default=[])
    job.add_argument("--output-dir", type=Path, default=Path("inferencex-contract"))
    job.add_argument("--repo-root", type=Path, default=Path.cwd())
    job.add_argument("--github-env", type=Path)
    job.add_argument("--github-output", type=Path)
    job.add_argument("--schema-dir", type=Path)
    job.set_defaults(handler=job_command)

    run = subparsers.add_parser("run")
    run.add_argument("--matrix-json")
    run.add_argument("--matrix-file", type=Path)
    run.add_argument("--output", type=Path, default=Path("inferencex-run-manifest.json"))
    run.add_argument("--repo-root", type=Path, default=Path.cwd())
    run.add_argument("--schema-dir", type=Path)
    run.set_defaults(handler=run_command)
    return result


def main() -> int:
    args = parser().parse_args()
    if getattr(args, "phase", None) == "final" and args.conclusion is None:
        raise SystemExit("--conclusion is required for a final manifest")
    if getattr(args, "phase", None) == "planned" and args.result:
        raise SystemExit("A planned manifest cannot contain results")
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

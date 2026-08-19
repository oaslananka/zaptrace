#!/usr/bin/env python3
"""Validate ZapTrace's machine-readable distribution support policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

_REQUIRED_TARGET_FIELDS = (
    "target_id",
    "operating_system",
    "architecture",
    "python",
    "artifact_type",
    "platform_tag",
    "native_extension",
    "support_level",
    "distribution_channel",
    "verification_workflow",
    "guidance",
)
_ALLOWED_SUPPORT_LEVELS = {"supported", "best-effort", "unsupported"}
_ALLOWED_NATIVE_STATES = {"required", "optional", "absent"}
_ALLOWED_ARTIFACT_TYPES = {"native-wheel", "source-distribution", "container-image"}


class DistributionPolicyError(ValueError):
    """Raised when a distribution policy cannot be trusted."""


class UnsupportedTargetError(DistributionPolicyError):
    """Raised when strict verification selects an unsupported target."""


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validated_policy_path(path: Path, *, allowed_root: Path) -> Path:
    root = allowed_root.resolve(strict=True)
    candidate = path if path.is_absolute() else root / path
    lexical = Path(os.path.abspath(candidate))
    for segment in (lexical, *lexical.parents):
        if segment.is_symlink():
            raise DistributionPolicyError(
                f"Distribution support policy path must not contain a symbolic link: {segment}"
            )
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise DistributionPolicyError(f"Cannot resolve distribution support policy {path}: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise DistributionPolicyError(f"Distribution support policy is outside allowed root {root}: {resolved}")
    if not resolved.is_file():
        raise DistributionPolicyError(f"Distribution support policy is not a regular file: {resolved}")
    if resolved.suffix.lower() != ".json":
        raise DistributionPolicyError(f"Distribution support policy must use .json: {resolved}")
    return resolved


def load_policy(path: Path, *, allowed_root: Path) -> dict[str, Any]:
    """Load a workspace-bounded JSON support policy from disk."""
    resolved = _validated_policy_path(path, allowed_root=allowed_root)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistributionPolicyError(f"Cannot load distribution support policy {resolved}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DistributionPolicyError("Distribution support policy root must be an object")
    return payload


def _required_field_errors(row: dict[str, Any], index: int) -> list[str]:
    return [
        f"targets[{index}].{field} must be a string"
        for field in _REQUIRED_TARGET_FIELDS
        if field not in row or not isinstance(row[field], str)
    ]


def _enum_errors(row: dict[str, str], index: int) -> list[str]:
    errors: list[str] = []
    constraints = (
        ("support_level", _ALLOWED_SUPPORT_LEVELS),
        ("native_extension", _ALLOWED_NATIVE_STATES),
        ("artifact_type", _ALLOWED_ARTIFACT_TYPES),
    )
    for field, allowed in constraints:
        if row[field].strip() not in allowed:
            errors.append(f"targets[{index}].{field} must be one of {sorted(allowed)}")
    return errors


def _identity_errors(row: dict[str, str], index: int) -> list[str]:
    return [
        f"targets[{index}].{field} must not be empty"
        for field in ("target_id", "operating_system", "architecture", "python")
        if not row[field].strip()
    ]


def _support_contract_errors(row: dict[str, str], index: int) -> list[str]:
    support_level = row["support_level"].strip()
    errors: list[str] = []
    if support_level == "supported" and not row["verification_workflow"].strip():
        errors.append(f"targets[{index}].verification_workflow is required for supported targets")
    if support_level == "unsupported" and not row["guidance"].strip():
        errors.append(f"targets[{index}].guidance is required for unsupported targets")
    return errors


def _validate_target(row: object, index: int) -> list[str]:
    if not isinstance(row, dict):
        return [f"targets[{index}] must be an object"]
    required_errors = _required_field_errors(row, index)
    if required_errors:
        return required_errors
    typed_row: dict[str, str] = {field: row[field] for field in _REQUIRED_TARGET_FIELDS}
    return [
        *_enum_errors(typed_row, index),
        *_identity_errors(typed_row, index),
        *_support_contract_errors(typed_row, index),
    ]


def validate_policy(policy: dict[str, Any]) -> list[str]:
    """Return deterministic validation errors for a distribution policy."""
    errors: list[str] = []
    if policy.get("schema_version") != "1.0":
        errors.append("schema_version must be '1.0'")
    if policy.get("package") != "zaptrace":
        errors.append("package must be 'zaptrace'")
    targets = policy.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append("targets must be a non-empty array")
        return errors

    seen: set[str] = set()
    for index, row in enumerate(targets):
        errors.extend(_validate_target(row, index))
        if not isinstance(row, dict):
            continue
        target_id = row.get("target_id")
        if not isinstance(target_id, str) or not target_id.strip():
            continue
        if target_id in seen:
            errors.append(f"duplicate target_id: {target_id}")
        seen.add(target_id)
    return sorted(errors)


def select_target(
    policy: dict[str, Any],
    target_id: str,
    *,
    require_supported: bool = False,
) -> dict[str, Any]:
    """Return one policy row and optionally reject unsupported claims."""
    errors = validate_policy(policy)
    if errors:
        raise DistributionPolicyError("Invalid distribution support policy: " + "; ".join(errors))
    targets = policy["targets"]
    for row in targets:
        if row["target_id"] != target_id:
            continue
        if require_supported and row["support_level"] == "unsupported":
            raise UnsupportedTargetError(f"Target {target_id} is unsupported. {row['guidance']}")
        return dict(row)
    raise DistributionPolicyError(f"Unknown distribution target: {target_id}")


def build_report(policy_path: Path, policy: dict[str, Any], target_id: str) -> dict[str, Any]:
    """Build deterministic validation evidence for one target."""
    errors = validate_policy(policy)
    target: dict[str, Any] | None = None
    if not errors:
        try:
            target = select_target(policy, target_id)
        except DistributionPolicyError as exc:
            errors.append(str(exc))
    canonical_policy = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema_version": "1.0",
        "gate_id": "distribution-support-policy-v1",
        "passed": not errors,
        "policy_path": policy_path.as_posix(),
        "policy_sha256": _sha256_bytes(canonical_policy),
        "target": target,
        "errors": sorted(errors),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--strict", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        policy = load_policy(args.policy, allowed_root=args.workspace)
        report = build_report(args.policy, policy, args.target)
    except DistributionPolicyError as exc:
        report = {
            "schema_version": "1.0",
            "gate_id": "distribution-support-policy-v1",
            "passed": False,
            "policy_path": args.policy.as_posix(),
            "policy_sha256": "",
            "target": None,
            "errors": [str(exc)],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 1 if args.strict and not report["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

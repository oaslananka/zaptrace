"""Deterministic bounded fuzz campaign runner."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal, cast

from zaptrace.security.fuzz_targets import TARGETS, FuzzRejectError

Profile = Literal["ci", "deep"]
Status = Literal["accept", "reject", "crash", "timeout", "resource_limit", "recursion"]
FAILURE_STATUSES = frozenset({"crash", "timeout", "resource_limit", "recursion"})
ALL_STATUSES: tuple[Status, ...] = ("accept", "reject", "crash", "timeout", "resource_limit", "recursion")
_MAX_PAYLOAD_BYTES = 131_072
_MAX_CHILD_PACKET_BYTES = 2 * _MAX_PAYLOAD_BYTES
_MAX_CASES_PER_SEED = 128
_MIN_TIMEOUT_SECONDS = 0.1
_MAX_TIMEOUT_SECONDS = 60.0
_MIN_MEMORY_LIMIT_MB = 64
_MAX_MEMORY_LIMIT_MB = 4096
_TARGET_TIMEOUT_MINIMUMS: dict[str, float] = {
    "workspace_path": 6.0,
    "api_transaction_request": 12.0,
    "mcp_tool_parameters": 15.0,
}


@dataclass(frozen=True)
class FuzzCase:
    target: str
    seed_path: str
    mutation: str
    mutation_index: int
    payload_sha256: str
    case_id: str
    payload: bytes


@dataclass(frozen=True)
class FuzzResult:
    case_id: str
    target: str
    seed_path: str
    mutation: str
    mutation_index: int
    payload_sha256: str
    payload_size: int
    status: Status
    detail: str = ""
    exception_type: str = ""
    elapsed_ms: int = 0
    failure_path: str = ""


def _resolve_within(root: str | Path, candidate: str | Path, *, require_file: bool = False) -> Path:
    """Return a canonical path contained by an explicitly trusted root."""
    canonical_root = Path(root).resolve()
    raw = Path(candidate)
    resolved = (raw if raw.is_absolute() else canonical_root / raw).resolve()
    try:
        resolved.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError(f"path escapes trusted root: {candidate}") from exc
    if require_file and not resolved.is_file():
        raise ValueError(f"required file does not exist: {candidate}")
    return resolved


def _validate_manifest(raw: object) -> list[dict[str, Any]]:
    targets = raw.get("targets") if isinstance(raw, dict) else None
    if not isinstance(targets, list) or not targets:
        raise ValueError("fuzz manifest must contain a non-empty targets list")
    seen: set[str] = set()
    for item in targets:
        if not isinstance(item, dict):
            raise ValueError("fuzz target entries must be objects")
        name = item.get("name")
        seed_paths = item.get("seed_paths")
        if not isinstance(name, str) or not name or name in seen or name not in TARGETS:
            raise ValueError(f"invalid, duplicate, or unknown fuzz target: {name!r}")
        if (
            not isinstance(seed_paths, list)
            or not seed_paths
            or not all(isinstance(value, str) and bool(value) for value in seed_paths)
        ):
            raise ValueError(f"fuzz target {name!r} must provide seed_paths")
        if len(seed_paths) != len(set(seed_paths)):
            raise ValueError(f"fuzz target {name!r} contains duplicate seed_paths")
        seen.add(name)
    return cast(list[dict[str, Any]], targets)


def load_manifest(path: str | Path, repository_root: str | Path) -> list[dict[str, Any]]:
    """Load a manifest only after canonical repository-root containment."""
    manifest_path = _resolve_within(repository_root, path, require_file=True)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    return _validate_manifest(raw)


def _chunk_bounds(payload: bytearray, rng: random.Random) -> tuple[int, int]:
    start = rng.randrange(len(payload))
    maximum = min(128, len(payload) - start)
    return start, min(len(payload), start + rng.randrange(1, maximum + 1))


def _mutate_chunk(operation: str, payload: bytearray, rng: random.Random) -> None:
    start, end = _chunk_bounds(payload, rng)
    if operation == "delete_chunk":
        del payload[start:end]
    elif operation == "duplicate_chunk":
        position = rng.randrange(len(payload) + 1)
        payload[position:position] = payload[start:end]
    else:
        payload[start:end] = reversed(payload[start:end])


def _mutate_token(operation: str, payload: bytearray, rng: random.Random, tokens: tuple[bytes, ...]) -> None:
    token = rng.choice(tokens)
    if operation == "prepend_token":
        payload[:0] = token
    elif operation == "append_token":
        payload.extend(token)
    else:
        position = rng.randrange(len(payload) + 1)
        payload[position:position] = token


def mutate(seed: bytes, rng: random.Random, index: int) -> tuple[str, bytes]:
    if index == 0:
        return "identity", seed[:_MAX_PAYLOAD_BYTES]
    operations = (
        "truncate",
        "delete_chunk",
        "duplicate_chunk",
        "flip_byte",
        "insert_token",
        "prepend_token",
        "append_token",
        "reverse_chunk",
        "byte_noise",
        "nesting",
    )
    operation = operations[(index - 1) % len(operations)]
    payload = bytearray(seed[:65_536])
    tokens = (b"\x00", b"../", b"..\\", b"{}", b"[]", b"()", b"<xml>", b"\xff\xfe", b"A" * 128)

    if operation == "truncate":
        limit = rng.randrange(0, len(payload) + 1) if payload else 0
        payload = payload[:limit]
    elif operation in {"delete_chunk", "duplicate_chunk", "reverse_chunk"} and payload:
        _mutate_chunk(operation, payload, rng)
    elif operation == "flip_byte" and payload:
        position = rng.randrange(len(payload))
        payload[position] ^= 1 << rng.randrange(8)
    elif operation in {"insert_token", "prepend_token", "append_token"}:
        _mutate_token(operation, payload, rng, tokens)
    elif operation == "byte_noise":
        position = rng.randrange(len(payload) + 1)
        payload[position:position] = bytes(rng.randrange(256) for _ in range(rng.randrange(1, 17)))
    elif operation == "nesting":
        depth = 8 + (index % 24)
        payload = bytearray(b"[" * depth + bytes(payload[:2048]) + b"]" * depth)
    return operation, bytes(payload[:_MAX_PAYLOAD_BYTES])


def _case_id(target: str, seed_path: str, mutation: str, index: int, payload: bytes) -> str:
    value = json.dumps(
        {
            "target": target,
            "seed_path": seed_path,
            "mutation": mutation,
            "mutation_index": index,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(value).hexdigest()[:24]


def build_cases(
    manifest_path: str | Path,
    repository_root: str | Path,
    campaign_seed: int,
    cases_per_seed: int,
    selected_targets: set[str] | None = None,
) -> tuple[FuzzCase, ...]:
    root = Path(repository_root).resolve()
    cases: list[FuzzCase] = []
    for target in load_manifest(manifest_path, root):
        name = target["name"]
        if selected_targets and name not in selected_targets:
            continue
        for relative in target["seed_paths"]:
            seed_path = _resolve_within(root, relative, require_file=True)
            with seed_path.open("rb") as seed_file:
                seed = seed_file.read(_MAX_PAYLOAD_BYTES + 1)
            if len(seed) > _MAX_PAYLOAD_BYTES:
                raise ValueError(f"fuzz seed exceeds {_MAX_PAYLOAD_BYTES} bytes: {relative}")
            key = hashlib.sha256(f"{campaign_seed}:{name}:{relative}".encode()).digest()
            rng = random.Random(int.from_bytes(key[:8], "big"))
            for index in range(cases_per_seed):
                mutation_name, payload = mutate(seed, rng, index)
                digest = hashlib.sha256(payload).hexdigest()
                cases.append(
                    FuzzCase(
                        target=name,
                        seed_path=relative,
                        mutation=mutation_name,
                        mutation_index=index,
                        payload_sha256=digest,
                        case_id=_case_id(name, relative, mutation_name, index, payload),
                        payload=payload,
                    )
                )
    return tuple(cases)


def execute_target(target: str, payload: bytes) -> tuple[Status, str, str]:
    """Execute one registered target inside a private temporary workspace."""
    executor = TARGETS.get(target)
    if executor is None:
        return "crash", f"unknown target: {target}", "UnknownTarget"
    with tempfile.TemporaryDirectory(prefix="zaptrace-fuzz-target-") as temporary:
        workspace = Path(temporary) / "workspace"
        workspace.mkdir()
        try:
            executor(payload, workspace)
        except FuzzRejectError as exc:
            cause = exc.__cause__
            return "reject", str(exc), type(cause).__name__ if cause else type(exc).__name__
        except MemoryError as exc:
            return "resource_limit", str(exc), type(exc).__name__
        except RecursionError as exc:
            return "recursion", str(exc), type(exc).__name__
        except Exception as exc:  # noqa: BLE001
            return "crash", str(exc), type(exc).__name__
    return "accept", "", ""


def apply_limits(memory_limit_mb: int, timeout_seconds: float) -> None:
    if os.name != "posix":
        return
    try:
        import resource

        memory_bytes = memory_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        cpu_seconds = max(1, math.ceil(timeout_seconds) + 1)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    except (ImportError, OSError, ValueError):
        return


def _child_packet(case: FuzzCase, timeout_seconds: float, memory_limit_mb: int) -> str:
    return json.dumps(
        {
            "target": case.target,
            "payload": base64.b64encode(case.payload).decode("ascii"),
            "timeout_seconds": timeout_seconds,
            "memory_limit_mb": memory_limit_mb,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def run_isolated(case: FuzzCase, timeout_seconds: float, memory_limit_mb: int) -> FuzzResult:
    started = time.monotonic()
    command = (sys.executable, "-m", "zaptrace.security.fuzz_campaign", "--child")
    try:
        completed = subprocess.run(
            command,
            input=_child_packet(case, timeout_seconds, memory_limit_mb),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _result(case, "timeout", "case exceeded timeout", "TimeoutExpired", started)

    if completed.returncode < 0:
        status: Status = "resource_limit" if completed.returncode in {-9, -24} else "crash"
        return _result(case, status, f"child signal {-completed.returncode}", "ChildSignal", started)
    try:
        child = json.loads(completed.stdout)
        status = child["status"]
        if status not in ALL_STATUSES:
            raise ValueError(f"invalid child status: {status!r}")
    except (KeyError, TypeError, ValueError) as exc:
        detail = completed.stderr.strip() or completed.stdout.strip() or str(exc)
        return _result(case, "crash", detail[:1000], "InvalidChildResult", started)
    return _result(
        case,
        status,
        str(child.get("detail", ""))[:1000],
        str(child.get("exception_type", ""))[:200],
        started,
    )


def _result(case: FuzzCase, status: Status, detail: str, exception_type: str, started: float) -> FuzzResult:
    return FuzzResult(
        case_id=case.case_id,
        target=case.target,
        seed_path=case.seed_path,
        mutation=case.mutation,
        mutation_index=case.mutation_index,
        payload_sha256=case.payload_sha256,
        payload_size=len(case.payload),
        status=status,
        detail=detail,
        exception_type=exception_type,
        elapsed_ms=round((time.monotonic() - started) * 1000),
    )


def stable_campaign_hash(
    results: Sequence[FuzzResult],
    profile: Profile,
    seed: int,
    *,
    cases_per_seed: int,
    timeout_seconds: float,
    memory_limit_mb: int,
    target_timeout_minimums: Mapping[str, float],
) -> str:
    cases = [
        {
            "case_id": item.case_id,
            "target": item.target,
            "seed_path": item.seed_path,
            "mutation": item.mutation,
            "mutation_index": item.mutation_index,
            "payload_sha256": item.payload_sha256,
            "status": item.status,
            "exception_type": item.exception_type,
        }
        for item in results
    ]
    value = json.dumps(
        {
            "schema_version": "1.0",
            "profile": profile,
            "campaign_seed": seed,
            "cases_per_seed": cases_per_seed,
            "timeout_seconds": timeout_seconds,
            "memory_limit_mb": memory_limit_mb,
            "target_timeout_minimums": dict(sorted(target_timeout_minimums.items())),
            "cases": cases,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(value).hexdigest()


def validate_campaign_policy(
    cases_per_seed: int,
    timeout_seconds: float,
    memory_limit_mb: int,
    selected_targets: set[str] | None,
) -> tuple[int, float, int, set[str] | None]:
    """Validate parent-side campaign bounds before allocating or spawning."""
    if (
        isinstance(cases_per_seed, bool)
        or not isinstance(cases_per_seed, int)
        or not 1 <= cases_per_seed <= _MAX_CASES_PER_SEED
    ):
        raise ValueError(f"cases_per_seed must be an integer between 1 and {_MAX_CASES_PER_SEED}")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not _MIN_TIMEOUT_SECONDS <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
    ):
        raise ValueError(f"timeout_seconds must be between {_MIN_TIMEOUT_SECONDS} and {_MAX_TIMEOUT_SECONDS}")
    if (
        isinstance(memory_limit_mb, bool)
        or not isinstance(memory_limit_mb, int)
        or not _MIN_MEMORY_LIMIT_MB <= memory_limit_mb <= _MAX_MEMORY_LIMIT_MB
    ):
        raise ValueError(
            f"memory_limit_mb must be an integer between {_MIN_MEMORY_LIMIT_MB} and {_MAX_MEMORY_LIMIT_MB}"
        )
    if selected_targets is not None:
        if not isinstance(selected_targets, set) or not selected_targets:
            raise ValueError("selected_targets must be a non-empty set")
        if not all(isinstance(target, str) for target in selected_targets):
            raise ValueError("selected_targets must contain only strings")
        unknown = sorted(selected_targets.difference(TARGETS))
        if unknown:
            raise ValueError(f"unknown selected_targets: {', '.join(unknown)}")
        selected_targets = set(selected_targets)
    return cases_per_seed, timeout_seconds, memory_limit_mb, selected_targets


def timeout_for_target(target: str, default_timeout: float) -> float:
    """Return the bounded timeout for a target, preserving stricter defaults."""
    return max(default_timeout, _TARGET_TIMEOUT_MINIMUMS.get(target, default_timeout))


def _profile_cases(profile: Profile, override: int | None) -> int:
    if override is not None:
        return override
    return 4 if profile == "ci" else 32


def _profile_timeout(profile: Profile, override: float | None) -> float:
    if override is not None:
        return override
    return 6.0 if profile == "ci" else 10.0


def run_campaign(
    manifest_path: str | Path,
    repository_root: str | Path,
    profile: Profile = "ci",
    campaign_seed: int = 8201,
    cases_per_seed: int | None = None,
    timeout_seconds: float | None = None,
    memory_limit_mb: int = 1024,
    selected_targets: set[str] | None = None,
) -> dict[str, Any]:
    """Run a campaign in memory; the fixed CLI layer persists evidence."""
    if profile not in {"ci", "deep"}:
        raise ValueError(f"unsupported profile: {profile}")
    root = Path(repository_root).resolve()
    effective_cases = _profile_cases(profile, cases_per_seed)
    effective_timeout = _profile_timeout(profile, timeout_seconds)
    effective_cases, effective_timeout, memory_limit_mb, selected_targets = validate_campaign_policy(
        effective_cases,
        effective_timeout,
        memory_limit_mb,
        selected_targets,
    )
    cases = build_cases(manifest_path, root, campaign_seed, effective_cases, selected_targets)
    if not cases:
        raise ValueError("campaign produced no cases")
    case_payloads = {case.case_id: case.payload for case in cases}
    results = [
        run_isolated(case, timeout_for_target(case.target, effective_timeout), memory_limit_mb) for case in cases
    ]

    counts = {status: sum(item.status == status for item in results) for status in ALL_STATUSES}
    target_counts: dict[str, dict[Status, int]] = {}
    empty_counts: dict[Status, int] = dict.fromkeys(ALL_STATUSES, 0)
    for item in results:
        bucket = target_counts.setdefault(item.target, empty_counts.copy())
        bucket[item.status] += 1
    failures: list[dict[str, Any]] = []
    for item in results:
        if item.status not in FAILURE_STATUSES:
            continue
        row = asdict(item)
        row["payload_base64"] = base64.b64encode(case_payloads[item.case_id]).decode("ascii")
        failures.append(row)
    applied_timeout_minimums = {
        target: _TARGET_TIMEOUT_MINIMUMS[target]
        for target in sorted(target_counts)
        if target in _TARGET_TIMEOUT_MINIMUMS
    }
    campaign_hash = stable_campaign_hash(
        results,
        profile,
        campaign_seed,
        cases_per_seed=effective_cases,
        timeout_seconds=effective_timeout,
        memory_limit_mb=memory_limit_mb,
        target_timeout_minimums=applied_timeout_minimums,
    )
    return {
        "schema_version": "1.0",
        "passed": not failures,
        "profile": profile,
        "campaign_seed": campaign_seed,
        "cases_per_seed": effective_cases,
        "timeout_seconds": effective_timeout,
        "target_timeout_minimums": applied_timeout_minimums,
        "memory_limit_mb": memory_limit_mb,
        "target_count": len(target_counts),
        "case_count": len(results),
        "counts": counts,
        "target_counts": target_counts,
        "failures": failures,
        "cases": [asdict(item) for item in results],
        "campaign_hash": campaign_hash,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


def _bounded_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    if not isinstance(value, (str, int, float)):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _bounded_float(value: object, *, minimum: float, maximum: float, default: float) -> float:
    if not isinstance(value, (str, int, float)):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _read_child_packet() -> tuple[str, bytes, int, float]:
    raw = sys.stdin.buffer.read(_MAX_CHILD_PACKET_BYTES + 1)
    if len(raw) > _MAX_CHILD_PACKET_BYTES:
        raise ValueError("child packet exceeds size limit")
    packet = json.loads(raw)
    if not isinstance(packet, Mapping):
        raise ValueError("child packet must be an object")
    target = packet.get("target")
    payload_text = packet.get("payload")
    if not isinstance(target, str) or target not in TARGETS:
        raise ValueError("child packet contains unknown target")
    if not isinstance(payload_text, str):
        raise ValueError("child packet payload must be base64 text")
    payload = base64.b64decode(payload_text, validate=True)
    if len(payload) > _MAX_PAYLOAD_BYTES:
        raise ValueError("child payload exceeds size limit")
    memory_limit = _bounded_int(packet.get("memory_limit_mb"), minimum=64, maximum=4096, default=1024)
    timeout = _bounded_float(packet.get("timeout_seconds"), minimum=0.1, maximum=60.0, default=6.0)
    return target, payload, memory_limit, timeout


def child_main() -> int:
    try:
        target, payload, memory_limit, timeout = _read_child_packet()
        apply_limits(memory_limit, timeout)
        status, detail, exception_type = execute_target(target, payload)
    except Exception as exc:  # noqa: BLE001
        status, detail, exception_type = "crash", str(exc), type(exc).__name__
    print(json.dumps({"status": status, "detail": detail, "exception_type": exception_type}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="ZapTrace isolated fuzz target executor")
    result.add_argument("--child", action="store_true")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    if not arguments.child:
        raise SystemExit("fuzz campaign module only supports isolated child mode")
    return child_main()


if __name__ == "__main__":
    raise SystemExit(main())

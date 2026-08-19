"""Tests for deterministic bounded fuzz campaign infrastructure."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import random
import subprocess
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from scripts import ci_fuzz_campaign
from zaptrace.export.path_policy import safe_export_stem
from zaptrace.security import fuzz_campaign
from zaptrace.security.fuzz_campaign import FuzzCase, FuzzResult, build_cases, execute_target, load_manifest, mutate

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "corpus" / "fuzz" / "manifest.json"


def test_manifest_covers_required_untrusted_boundaries() -> None:
    names = {item["name"] for item in load_manifest(MANIFEST, ROOT)}

    assert names == {
        "design_yaml",
        "requirements_schema",
        "kicad_schematic",
        "kicad_pcb",
        "easyeda_std",
        "easyeda_pro_zip",
        "eagle_xml",
        "altium_ascii",
        "plugin_manifest",
        "workspace_path",
        "gerber_prefix",
        "excellon_prefix",
        "api_transaction_request",
        "mcp_tool_parameters",
    }


def test_case_generation_is_deterministic_and_seeded() -> None:
    first = build_cases(MANIFEST, ROOT, 8201, 3)
    second = build_cases(MANIFEST, ROOT, 8201, 3)
    changed = build_cases(MANIFEST, ROOT, 8202, 3)

    assert [(case.case_id, case.payload) for case in first] == [(case.case_id, case.payload) for case in second]
    assert [case.case_id for case in first] != [case.case_id for case in changed]


def test_mutations_are_size_bounded() -> None:
    seed = b"seed" * 40_000
    rng = random.Random(82)

    for index in range(40):
        _name, payload = mutate(seed, rng, index)
        assert len(payload) <= 131_072


def test_valid_seed_identity_cases_do_not_crash() -> None:
    cases = build_cases(MANIFEST, ROOT, 8201, 1)

    for case in cases:
        status, _detail, _exception = execute_target(case.target, case.payload)
        assert status in {"accept", "reject"}, case.target


def test_subprocess_timeout_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    case = FuzzCase(
        target="design_yaml",
        seed_path="seed.yaml",
        mutation="identity",
        mutation_index=0,
        payload_sha256="0" * 64,
        case_id="case-timeout",
        payload=b"meta: {name: demo}",
    )

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="fuzz-child", timeout=0.01)

    monkeypatch.setattr(subprocess, "run", timeout)
    result = fuzz_campaign.run_isolated(case, timeout_seconds=0.01, memory_limit_mb=128)

    assert result.status == "timeout"
    assert result.exception_type == "TimeoutExpired"


def test_campaign_preserves_failure_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def crash(case: FuzzCase, _timeout: float, _memory: int) -> FuzzResult:
        return FuzzResult(
            case_id=case.case_id,
            target=case.target,
            seed_path=case.seed_path,
            mutation=case.mutation,
            mutation_index=case.mutation_index,
            payload_sha256=case.payload_sha256,
            payload_size=len(case.payload),
            status="crash",
            detail="synthetic crash",
            exception_type="SyntheticError",
        )

    monkeypatch.setattr(fuzz_campaign, "run_isolated", crash)
    report = fuzz_campaign.run_campaign(
        MANIFEST,
        ROOT,
        cases_per_seed=1,
        selected_targets={"plugin_manifest"},
    )

    assert report["passed"] is False
    payload = base64.b64decode(report["failures"][0]["payload_base64"], validate=True)
    assert payload == (ROOT / "tests/fixtures/plugins/valid/zaptrace-plugin.json").read_bytes()


def test_small_campaign_report_is_reproducible() -> None:
    first = fuzz_campaign.run_campaign(
        MANIFEST,
        ROOT,
        cases_per_seed=2,
        selected_targets={"plugin_manifest", "workspace_path"},
        timeout_seconds=3,
    )
    second = fuzz_campaign.run_campaign(
        MANIFEST,
        ROOT,
        cases_per_seed=2,
        selected_targets={"plugin_manifest", "workspace_path"},
        timeout_seconds=3,
    )

    assert first["passed"] is True
    assert first["campaign_hash"] == second["campaign_hash"]
    assert first["case_count"] == 4
    assert first["schema_version"] == "1.0"


@pytest.mark.parametrize(
    "target",
    [
        "design_yaml",
        "requirements_schema",
        "kicad_schematic",
        "easyeda_std",
        "easyeda_pro_zip",
        "eagle_xml",
        "altium_ascii",
        "plugin_manifest",
        "api_transaction_request",
        "mcp_tool_parameters",
    ],
)
@given(payload=st.binary(max_size=512))
@settings(max_examples=12, deadline=None)
def test_text_and_binary_boundaries_only_accept_or_reject(target: str, payload: bytes) -> None:
    digest = hashlib.sha256(payload).hexdigest()
    case = FuzzCase(
        target=target,
        seed_path="hypothesis",
        mutation="hypothesis",
        mutation_index=0,
        payload_sha256=digest,
        case_id=digest[:24],
        payload=payload,
    )
    result = fuzz_campaign.run_isolated(
        case,
        timeout_seconds=fuzz_campaign.timeout_for_target(target, 10.0),
        memory_limit_mb=512,
    )
    assert result.status in {"accept", "reject"}, (target, result.status, result.exception_type, result.detail)


@pytest.mark.parametrize("target", ["gerber_prefix", "excellon_prefix"])
@given(prefix=st.text(max_size=128))
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_export_prefixes_remain_single_contained_stems(target: str, prefix: str) -> None:
    status, detail, _exception = execute_target(target, prefix.encode())

    assert status == "accept", detail
    stem = safe_export_stem(prefix)
    assert "/" not in stem
    assert "\\" not in stem
    assert stem not in {"", ".", ".."}


def test_path_and_manifest_guards_reject_untrusted_shapes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes trusted root"):
        fuzz_campaign._resolve_within(tmp_path, "../escape")
    with pytest.raises(ValueError, match="required file"):
        fuzz_campaign._resolve_within(tmp_path, "missing.json", require_file=True)

    invalid_manifests = [
        None,
        {"targets": ["not-an-object"]},
        {"targets": [{"name": "unknown", "seed_paths": ["seed"]}]},
        {"targets": [{"name": "design_yaml", "seed_paths": []}]},
        {"targets": [{"name": "design_yaml", "seed_paths": ["seed", "seed"]}]},
        {
            "targets": [
                {"name": "design_yaml", "seed_paths": ["seed-a"]},
                {"name": "design_yaml", "seed_paths": ["seed-b"]},
            ]
        },
    ]
    for manifest in invalid_manifests:
        with pytest.raises(ValueError):
            fuzz_campaign._validate_manifest(manifest)


def test_execute_target_classifies_registered_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    assert execute_target("missing-target", b"")[0:3:2] == ("crash", "UnknownTarget")

    def reject(_payload: bytes, _workspace: Path) -> None:
        try:
            raise ValueError("malformed")
        except ValueError as exc:
            raise fuzz_campaign.FuzzRejectError("rejected") from exc

    def exhaust_memory(_payload: bytes, _workspace: Path) -> None:
        raise MemoryError("bounded")

    def recurse(_payload: bytes, _workspace: Path) -> None:
        raise RecursionError("bounded")

    def crash(_payload: bytes, _workspace: Path) -> None:
        raise RuntimeError("unexpected")

    for name, executor, expected in (
        ("test-reject", reject, ("reject", "ValueError")),
        ("test-memory", exhaust_memory, ("resource_limit", "MemoryError")),
        ("test-recursion", recurse, ("recursion", "RecursionError")),
        ("test-crash", crash, ("crash", "RuntimeError")),
    ):
        monkeypatch.setitem(fuzz_campaign.TARGETS, name, executor)
        status, _detail, exception_type = execute_target(name, b"payload")
        assert status == expected[0]
        assert exception_type == expected[1]


def test_run_isolated_classifies_child_protocol_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    case = FuzzCase(
        target="design_yaml",
        seed_path="seed.yaml",
        mutation="identity",
        mutation_index=0,
        payload_sha256="0" * 64,
        case_id="case-child-failure",
        payload=b"meta: {name: demo}",
    )

    outcomes = iter(
        [
            subprocess.CompletedProcess([], -9, "", ""),
            subprocess.CompletedProcess([], -11, "", ""),
            subprocess.CompletedProcess([], 0, '{"status":"unknown"}', ""),
            subprocess.CompletedProcess([], 0, "not-json", "child stderr"),
        ]
    )
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: next(outcomes))

    assert fuzz_campaign.run_isolated(case, 1.0, 128).status == "resource_limit"
    assert fuzz_campaign.run_isolated(case, 1.0, 128).status == "crash"
    assert fuzz_campaign.run_isolated(case, 1.0, 128).exception_type == "InvalidChildResult"
    result = fuzz_campaign.run_isolated(case, 1.0, 128)
    assert result.exception_type == "InvalidChildResult"
    assert result.detail == "child stderr"


def test_child_packet_bounds_and_entrypoints(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class InputPacket:
        def __init__(self, payload: bytes) -> None:
            self.buffer = io.BytesIO(payload)

    packet = json.dumps(
        {
            "target": "design_yaml",
            "payload": base64.b64encode(b"meta: {name: demo}").decode(),
            "memory_limit_mb": 1,
            "timeout_seconds": 100,
        }
    ).encode()
    monkeypatch.setattr(fuzz_campaign.sys, "stdin", InputPacket(packet))
    target, payload, memory_limit, timeout = fuzz_campaign._read_child_packet()
    assert (target, payload, memory_limit, timeout) == ("design_yaml", b"meta: {name: demo}", 64, 60.0)

    monkeypatch.setattr(fuzz_campaign.sys, "stdin", InputPacket(b"[]"))
    assert fuzz_campaign.child_main() == 0
    child_output = json.loads(capsys.readouterr().out)
    assert child_output["status"] == "crash"
    assert child_output["exception_type"] == "ValueError"

    with pytest.raises(SystemExit, match="isolated child mode"):
        fuzz_campaign.main([])
    monkeypatch.setattr(fuzz_campaign, "child_main", lambda: 7)
    assert fuzz_campaign.main(["--child"]) == 7


def test_campaign_policy_rejects_unbounded_or_empty_inputs() -> None:
    valid = fuzz_campaign.validate_campaign_policy(4, 6.0, 1024, {"design_yaml"})
    assert valid == (4, 6.0, 1024, {"design_yaml"})

    invalid = [
        (0, 6.0, 1024, {"design_yaml"}),
        (1.5, 6.0, 1024, {"design_yaml"}),
        (129, 6.0, 1024, {"design_yaml"}),
        (4, True, 1024, {"design_yaml"}),
        (4, 0.0, 1024, {"design_yaml"}),
        (4, 61.0, 1024, {"design_yaml"}),
        (4, 6.0, 63, {"design_yaml"}),
        (4, 6.0, 1024.5, {"design_yaml"}),
        (4, 6.0, 4097, {"design_yaml"}),
        (4, 6.0, 1024, set()),
        (4, 6.0, 1024, {"missing-target"}),
    ]
    for cases, timeout, memory, targets in invalid:
        with pytest.raises(ValueError):
            fuzz_campaign.validate_campaign_policy(cases, timeout, memory, targets)


def test_seed_files_are_bounded_before_case_generation(tmp_path: Path) -> None:
    seed = tmp_path / "seed.bin"
    seed.write_bytes(b"x" * 131_073)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"targets": [{"name": "design_yaml", "seed_paths": ["seed.bin"]}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="seed exceeds"):
        build_cases(manifest, tmp_path, 8201, 1)


def test_campaign_hash_binds_timeout_and_memory_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    def accept(case: FuzzCase, _timeout: float, _memory: int) -> FuzzResult:
        return FuzzResult(
            case_id=case.case_id,
            target=case.target,
            seed_path=case.seed_path,
            mutation=case.mutation,
            mutation_index=case.mutation_index,
            payload_sha256=case.payload_sha256,
            payload_size=len(case.payload),
            status="accept",
        )

    monkeypatch.setattr(fuzz_campaign, "run_isolated", accept)
    baseline = fuzz_campaign.run_campaign(
        MANIFEST,
        ROOT,
        cases_per_seed=1,
        timeout_seconds=6.0,
        memory_limit_mb=1024,
        selected_targets={"plugin_manifest"},
    )
    changed_timeout = fuzz_campaign.run_campaign(
        MANIFEST,
        ROOT,
        cases_per_seed=1,
        timeout_seconds=7.0,
        memory_limit_mb=1024,
        selected_targets={"plugin_manifest"},
    )
    changed_memory = fuzz_campaign.run_campaign(
        MANIFEST,
        ROOT,
        cases_per_seed=1,
        timeout_seconds=6.0,
        memory_limit_mb=2048,
        selected_targets={"plugin_manifest"},
    )
    assert baseline["campaign_hash"] != changed_timeout["campaign_hash"]
    assert baseline["campaign_hash"] != changed_memory["campaign_hash"]


def test_target_timeout_override_is_explicit_and_minimal() -> None:
    assert fuzz_campaign.timeout_for_target("design_yaml", 6.0) == pytest.approx(6.0)
    assert fuzz_campaign.timeout_for_target("workspace_path", 3.0) == pytest.approx(6.0)
    assert fuzz_campaign.timeout_for_target("api_transaction_request", 6.0) == pytest.approx(12.0)
    assert fuzz_campaign.timeout_for_target("mcp_tool_parameters", 6.0) == pytest.approx(15.0)
    assert fuzz_campaign.timeout_for_target("mcp_tool_parameters", 20.0) == pytest.approx(20.0)


def test_persist_evidence_uses_validated_case_id_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "artifacts" / "fuzz" / "campaign.json"
    failures = output.parent / "fuzz-failures"
    monkeypatch.setattr(ci_fuzz_campaign, "ROOT", tmp_path)
    monkeypatch.setattr(ci_fuzz_campaign, "DEFAULT_OUTPUT", output)
    monkeypatch.setattr(ci_fuzz_campaign, "DEFAULT_FAILURE_ROOT", failures)

    case_id = "a" * 24
    report = {
        "failures": [
            {
                "case_id": case_id,
                "payload_base64": base64.b64encode(b"reproducer").decode("ascii"),
            }
        ]
    }
    evidence = ci_fuzz_campaign.persist_evidence(report)
    expected = failures / f"{case_id}.bin"
    assert expected.read_bytes() == b"reproducer"
    assert evidence["failures"][0]["failure_path"] == expected.relative_to(tmp_path).as_posix()

    report["failures"][0]["case_id"] = "../escape"
    report["failures"][0]["payload_base64"] = base64.b64encode(b"bad").decode("ascii")
    with pytest.raises(ValueError, match="case_id"):
        ci_fuzz_campaign.persist_evidence(report)


def test_profile_defaults_and_invalid_profile() -> None:
    assert fuzz_campaign._profile_cases("deep", None) == 32
    assert fuzz_campaign._profile_timeout("deep", None) == pytest.approx(10.0)
    assert fuzz_campaign._bounded_int(None, minimum=1, maximum=9, default=4) == 4
    assert fuzz_campaign._bounded_int("bad", minimum=1, maximum=9, default=4) == 4
    assert fuzz_campaign._bounded_float(None, minimum=0.1, maximum=9.0, default=4.0) == pytest.approx(4.0)
    assert fuzz_campaign._bounded_float("bad", minimum=0.1, maximum=9.0, default=4.0) == pytest.approx(4.0)
    with pytest.raises(ValueError, match="unsupported profile"):
        fuzz_campaign.run_campaign(MANIFEST, ROOT, profile="invalid")  # type: ignore[arg-type]


def test_minimized_backslash_fixture_remains_single_byte_and_precommit_exempt() -> None:
    fixture = Path("tests/corpus/fuzz/seeds/kicad-standalone-backslash.kicad_sch")
    assert fixture.read_bytes() == b"\\"
    config = Path(".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "kicad-standalone-backslash\\.kicad_sch" in config


def test_fuzz_workflow_uses_locked_buildless_dependencies() -> None:
    workflow = Path(".github/workflows/fuzz.yml").read_text(encoding="utf-8")
    assert "uv sync --locked --all-extras --group test --no-install-project --no-build" in workflow
    assert 'PYTHONPATH: "."' in workflow
    assert ".venv/bin/python scripts/ci_fuzz_campaign.py" in workflow
    assert "uv run python scripts/ci_fuzz_campaign.py" not in workflow

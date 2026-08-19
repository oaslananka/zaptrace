"""Contract and fail-closed tests for the KiCad 10 jobset oracle."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import ci_kicad_jobset_oracle as oracle


def test_jobset_contract_is_deterministic_and_complete() -> None:
    first = oracle._canonical_json(oracle.build_jobset_contract())
    second = oracle._canonical_json(oracle.build_jobset_contract())
    assert first == second
    assert hashlib.sha256(first.encode()).hexdigest() == hashlib.sha256(second.encode()).hexdigest()
    payload = json.loads(first)
    assert [job["type"] for job in payload["jobs"]] == list(oracle._REQUIRED_JOB_TYPES)
    assert payload["outputs"][0]["only"] == [job["id"] for job in payload["jobs"]]


def test_contract_rejects_missing_required_job() -> None:
    payload = oracle.build_jobset_contract()
    payload["jobs"].pop()
    with pytest.raises(ValueError, match="inventory mismatch"):
        oracle.validate_jobset_contract(payload)


def test_kicad_version_is_strictly_10_x() -> None:
    oracle._require_kicad_10("10.0.5")
    for version in ("9.0.6", "11.0.0", "unknown"):
        with pytest.raises(RuntimeError, match="KiCad 10.x required"):
            oracle._require_kicad_10(version)


def test_artifact_validation_fails_when_job_output_is_partial(tmp_path: Path) -> None:
    (tmp_path / "erc.json").write_text("{}")
    (tmp_path / "drc.json").write_text("{}")
    with pytest.raises(RuntimeError, match="missing expected artifacts"):
        oracle._artifact_hashes(tmp_path, "board")


def test_artifact_validation_requires_gerber_layer(tmp_path: Path) -> None:
    for name in ("erc.json", "drc.json", "board.drl", "board-job.gbrjob"):
        (tmp_path / name).write_text("ok")
    with pytest.raises(RuntimeError, match="no Gerber layer"):
        oracle._artifact_hashes(tmp_path, "board")


def test_bounded_diagnostics_do_not_leak_unbounded_output() -> None:
    text = "x" * (oracle.DIAGNOSTIC_LIMIT + 100)
    bounded = oracle._bounded(text)
    assert bounded.endswith("...[diagnostics truncated]")
    assert len(bounded) < len(text)


def test_run_family_fails_closed_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oracle, "_family_source", lambda _family: (Path("/tmp/source"), "board"))
    monkeypatch.setattr(oracle, "_source_identity", lambda *_args: {"sha256": "a", "files": {}})
    monkeypatch.setattr(
        oracle,
        "_stage_project",
        lambda _s, _stem, w: {
            "project": w / "board.kicad_pro",
            "schematic": w / "board.kicad_sch",
            "pcb": w / "board.kicad_pcb",
        },
    )
    monkeypatch.setattr(
        oracle,
        "_run_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("kicad-cli", 1)),
    )
    with pytest.raises(RuntimeError, match="timed out"):
        oracle.run_family("board", cli="kicad-cli", version="10.0.5", timeout=1)


def test_run_family_fails_closed_on_nonzero_jobset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oracle, "_family_source", lambda _family: (Path("/tmp/source"), "board"))
    monkeypatch.setattr(oracle, "_source_identity", lambda *_args: {"sha256": "a", "files": {}})
    monkeypatch.setattr(
        oracle,
        "_stage_project",
        lambda _s, _stem, w: {
            "project": w / "board.kicad_pro",
            "schematic": w / "board.kicad_sch",
            "pcb": w / "board.kicad_pcb",
        },
    )
    completed = subprocess.CompletedProcess(["kicad-cli"], 6, "partial", "failed")
    monkeypatch.setattr(oracle, "_run_command", lambda *_args, **_kwargs: completed)
    with pytest.raises(RuntimeError, match="exit 6"):
        oracle.run_family("board", cli="kicad-cli", version="10.0.5")


def test_source_identity_detects_fixture_drift(tmp_path: Path) -> None:
    stem = "board"
    for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
        (tmp_path / f"{stem}{suffix}").write_text(suffix)
    before = oracle._source_identity(tmp_path, stem)
    (tmp_path / f"{stem}.kicad_pcb").write_text("changed")
    after = oracle._source_identity(tmp_path, stem)
    assert before["sha256"] != after["sha256"]


def test_main_rejects_output_outside_trusted_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside.json"
    assert oracle.main(["--output", str(outside)], trusted_root=trusted) == 1
    captured = capsys.readouterr()
    assert captured.err == "ERROR: KiCad jobset oracle failed\n"
    assert str(outside) not in captured.err


def _fake_staged_paths(workspace: Path) -> dict[str, Path]:
    paths = {
        "project": workspace / "board.kicad_pro",
        "schematic": workspace / "board.kicad_sch",
        "pcb": workspace / "board.kicad_pcb",
    }
    for path in paths.values():
        path.write_text("staged")
    return paths


def test_run_family_rejects_stale_source_identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
        (source / f"board{suffix}").write_text("source")
    identities = iter(({"sha256": "before", "files": {}}, {"sha256": "after", "files": {}}))
    monkeypatch.setattr(oracle, "_family_source", lambda _family: (source, "board"))
    monkeypatch.setattr(oracle, "_source_identity", lambda *_args: next(identities))
    monkeypatch.setattr(oracle, "_stage_project", lambda _s, _stem, workspace: _fake_staged_paths(workspace))
    monkeypatch.setattr(
        oracle, "_run_command", lambda *_args, **_kwargs: subprocess.CompletedProcess(["kicad-cli"], 0, "ok", "")
    )
    monkeypatch.setattr(oracle, "_artifact_hashes", lambda *_args: {"erc.json": "a", "drc.json": "b"})
    checks = {"erc": {"errors": 0, "warnings": 0}, "drc": {"errors": 0, "warnings": 0}}
    monkeypatch.setattr(oracle, "_jobset_check_summary", lambda *_args: checks)
    monkeypatch.setattr(oracle, "_focused_parity", lambda *_args, **_kwargs: {"passed": True, **checks})
    with pytest.raises(RuntimeError, match="identity changed"):
        oracle.run_family("board", cli="kicad-cli", version="10.0.5")


def test_portable_diagnostics_redact_machine_paths(tmp_path: Path) -> None:
    raw = f"Saved to {tmp_path}/result.json and /home/ubuntu/private/file.txt"
    portable = oracle._portable_diagnostics(raw, tmp_path)
    assert str(tmp_path) not in portable
    assert "/home/ubuntu" not in portable
    assert "<workspace>" in portable


def test_jobset_reports_match_focused_counts() -> None:
    jobset = {"erc": {"errors": 0, "warnings": 1}, "drc": {"errors": 0, "warnings": 0}}
    focused = {"erc": {"errors": 0, "warnings": 1}, "drc": {"errors": 0, "warnings": 0}}
    oracle._require_check_parity(jobset, focused)
    focused["erc"]["warnings"] = 2
    with pytest.raises(RuntimeError, match="ERC parity mismatch"):
        oracle._require_check_parity(jobset, focused)


def test_source_commit_prefers_explicit_pr_head(monkeypatch: pytest.MonkeyPatch) -> None:
    head = "a" * 40
    monkeypatch.setenv("ZAPTRACE_SOURCE_COMMIT", head)
    monkeypatch.setenv("GITHUB_SHA", "b" * 40)
    assert oracle._source_commit() == head


def test_required_quality_gate_runs_jobset_oracle_and_uploads_evidence() -> None:
    workflow = (oracle.ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    assert "Run atomic KiCad 10 jobset oracle" in workflow
    assert "scripts/ci_kicad_jobset_oracle.py --output kicad-jobset-oracle-summary.json" in workflow
    assert "kicad-jobset-oracle-summary.json" in workflow
    assert '--required-oracle "kicad-oracle"' in workflow


def test_jobset_change_is_classified_for_heavy_ci() -> None:
    from scripts.ci_change_policy import classify_paths

    policy = classify_paths(["scripts/ci_kicad_jobset_oracle.py"], event_name="pull_request")
    assert policy.heavy_ci is True
    assert policy.full_ci is True


def test_success_output_does_not_expose_evidence_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(oracle.shutil, "which", lambda _name: "/usr/bin/kicad-cli")
    monkeypatch.setattr(oracle, "build_report", lambda *_args, **_kwargs: {"status": "passed"})
    assert oracle.main(["--output", "safe-summary.json"], trusted_root=tmp_path) == 0
    captured = capsys.readouterr()
    assert captured.out == "KiCad jobset oracle passed for 3 family/families\n"
    assert str(tmp_path) not in captured.out


def _valid_odb_archive(path: Path) -> None:
    import zipfile

    members = {
        "matrix/matrix": b"matrix",
        "steps/pcb/profile": b"profile",
        "steps/pcb/stephdr": b"header",
        "steps/pcb/eda/data": b"eda",
        "steps/pcb/netlists/cadnet/netlist": b"netlist",
        "steps/pcb/layers/f.cu/features": b"features",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _valid_glb(path: Path) -> None:
    import json as _json
    import struct

    payload = _json.dumps({"asset": {"version": "2.0"}, "nodes": [{}], "meshes": [{}]}).encode()
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunk = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    body = b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk
    path.write_bytes(body)


def test_odb_archive_validation_records_safe_structure(tmp_path: Path) -> None:
    archive = tmp_path / "board-odb.zip"
    _valid_odb_archive(archive)
    evidence = oracle._validate_odb_archive(archive)
    assert evidence["member_count"] == 6
    assert evidence["unsafe_members"] == []
    assert evidence["structural_inventory_sha256"]
    assert evidence["byte_determinism"] == "not-guaranteed"


def test_odb_structural_inventory_is_stable_when_archive_bytes_change(tmp_path: Path) -> None:
    import zipfile

    members = {
        "matrix/matrix": b"matrix",
        "steps/pcb/profile": b"profile",
        "steps/pcb/stephdr": b"header",
        "steps/pcb/eda/data": b"eda",
        "steps/pcb/netlists/cadnet/netlist": b"netlist",
        "steps/pcb/layers/f.cu/features": b"features",
    }
    paths = [tmp_path / "first-odb.zip", tmp_path / "second-odb.zip"]
    for index, path in enumerate(paths):
        with zipfile.ZipFile(path, "w") as archive:
            for name, payload in members.items():
                if name == "matrix/matrix":
                    payload = b"matriA" if index == 0 else b"matriB"
                archive.writestr(name, payload)

    first = oracle._validate_odb_archive(paths[0])
    second = oracle._validate_odb_archive(paths[1])

    assert first["sha256"] != second["sha256"]
    assert first["member_inventory"] == second["member_inventory"]
    assert first["structural_inventory_sha256"] == second["structural_inventory_sha256"]
    assert first["byte_determinism"] == second["byte_determinism"] == "not-guaranteed"
    assert "semantic_inventory_sha256" not in first


def test_odb_archive_rejects_traversal_absolute_backslash_and_symlink(tmp_path: Path) -> None:
    import stat
    import zipfile

    for member in ("../escape", "/absolute", "..\\windows"):
        archive = tmp_path / f"unsafe-{len(list(tmp_path.iterdir()))}.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr(member, b"x")
        with pytest.raises(RuntimeError, match=r"unsafe ODB\+\+ archive member"):
            oracle._validate_odb_archive(archive)

    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("steps/pcb/profile")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr(info, "target")
    with pytest.raises(RuntimeError, match="symlink"):
        oracle._validate_odb_archive(archive)


def test_odb_archive_rejects_partial_or_empty_output(tmp_path: Path) -> None:
    import zipfile

    empty = tmp_path / "empty.zip"
    empty.write_bytes(b"")
    with pytest.raises(RuntimeError, match="not a valid ZIP"):
        oracle._validate_odb_archive(empty)

    partial = tmp_path / "partial.zip"
    with zipfile.ZipFile(partial, "w") as archive:
        archive.writestr("matrix/matrix", b"matrix")
    with pytest.raises(RuntimeError, match="missing required structure"):
        oracle._validate_odb_archive(partial)


def test_glb_validation_records_review_shape(tmp_path: Path) -> None:
    path = tmp_path / "board.glb"
    _valid_glb(path)
    evidence = oracle._validate_glb(path)
    assert evidence["version"] == 2
    assert evidence["declared_length"] == path.stat().st_size
    assert evidence["mesh_count"] == 1
    assert evidence["node_count"] == 1
    assert evidence["structural_shape_sha256"]
    assert evidence["byte_determinism"] == "not-guaranteed"


def test_glb_structural_shape_is_stable_when_payload_bytes_change(tmp_path: Path) -> None:
    import json as _json
    import struct

    def write_glb(path: Path, marker: str) -> None:
        payload = _json.dumps(
            {
                "asset": {"version": "2.0", "generator": marker},
                "nodes": [{"name": marker}],
                "meshes": [{"name": marker}],
                "materials": [{}],
                "accessors": [{}],
                "bufferViews": [{}],
                "buffers": [{}],
            }
        ).encode()
        payload += b" " * ((4 - len(payload) % 4) % 4)
        chunk = struct.pack("<II", len(payload), 0x4E4F534A) + payload
        path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk)

    first_path, second_path = tmp_path / "first.glb", tmp_path / "second.glb"
    write_glb(first_path, "A")
    write_glb(second_path, "B")
    first = oracle._validate_glb(first_path)
    second = oracle._validate_glb(second_path)

    assert first["sha256"] != second["sha256"]
    assert first["structural_shape"] == second["structural_shape"]
    assert first["structural_shape_sha256"] == second["structural_shape_sha256"]
    assert first["byte_determinism"] == second["byte_determinism"] == "not-guaranteed"


def test_glb_validation_fails_closed_on_bad_header_or_length(tmp_path: Path) -> None:
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"nope")
    with pytest.raises(RuntimeError, match="GLB header"):
        oracle._validate_glb(bad)

    mismatch = tmp_path / "mismatch.glb"
    _valid_glb(mismatch)
    data = bytearray(mismatch.read_bytes())
    data[8:12] = (len(data) + 4).to_bytes(4, "little")
    mismatch.write_bytes(data)
    with pytest.raises(RuntimeError, match="declared length"):
        oracle._validate_glb(mismatch)


def test_mechanical_coverage_never_claims_complete_from_unresolved_model_refs(tmp_path: Path) -> None:
    empty_board = tmp_path / "empty.kicad_pcb"
    empty_board.write_text("(kicad_pcb (version 20250114))\n")
    empty = oracle._mechanical_model_coverage(empty_board)
    assert empty["complete"] is False
    assert "no-footprints-in-exported-board" in empty["limitations"]

    missing = tmp_path / "missing.kicad_pcb"
    missing.write_text('(footprint "Package_QFN:QFN-32" (layer "F.Cu"))\n')
    result = oracle._mechanical_model_coverage(missing)
    assert result["complete"] is False
    assert result["footprint_count"] == 1
    assert result["model_reference_count"] == 0
    assert "missing-component-model-references" in result["limitations"]


def test_review_bundle_workflows_retain_exports() -> None:
    standalone = (oracle.ROOT / ".github/workflows/kicad-oracle.yml").read_text(encoding="utf-8")
    quality = (oracle.ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    for workflow in (standalone, quality):
        assert "kicad-review-exports" in workflow
        assert "kicad-jobset-oracle-summary.json" in workflow


def test_review_publish_is_atomic_across_family_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    final = tmp_path / "review"
    monkeypatch.setattr(oracle, "_kicad_version", lambda _cli: "10.0.5")

    def fake_run(
        family: str, *, cli: str, version: str, timeout: int, review_output_root: Path | None = None
    ) -> dict[str, object]:
        assert review_output_root is not None
        if family == "bad":
            raise RuntimeError("boom")
        family_dir = review_output_root / family
        family_dir.mkdir(parents=True)
        (family_dir / "partial.txt").write_text("partial")
        return {"family_id": family, "review_exports": {"status": "degraded"}}

    monkeypatch.setattr(oracle, "run_family", fake_run)
    with pytest.raises(RuntimeError, match="boom"):
        oracle.build_report(["good", "bad"], cli="kicad-cli", review_output_root=final)
    assert not final.exists()


def test_main_rejects_review_output_outside_trusted_root(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    outside = tmp_path / "outside-review"
    assert oracle.main(["--review-output-dir", str(outside)], trusted_root=trusted) == 1
    assert not outside.exists()
    assert capsys.readouterr().err == "ERROR: KiCad jobset oracle failed\n"


def test_published_review_index_is_proof_compatible_and_revision_bound(tmp_path: Path) -> None:
    from zaptrace.proof.manifest import ManufacturingExportEvidence

    source = tmp_path / "source"
    target = tmp_path / "retained"
    source.mkdir()
    _valid_odb_archive(source / "board-odb.zip")
    _valid_glb(source / "board.glb")
    evidence = {
        "status": "degraded",
        "odbpp": {"artifact": "board-odb.zip", "command": ["kicad-cli", "pcb", "export", "odb"]},
        "mechanical_review": {
            "artifact": "board.glb",
            "command": ["kicad-cli", "pcb", "export", "glb"],
            "coverage": {"model_reference_count": 0, "limitations": ["no-footprints-in-exported-board"]},
        },
        "non_claims": [],
        "_source_dir": str(source),
    }
    project_identity = {"sha256": "a" * 64, "files": {}}
    published = oracle._publish_review_family(
        target, "board", "10.0.5", project_identity, {"board-F_Cu.gbr": "b" * 64}, evidence
    )
    assert published["source_commit"]
    assert published["project_identity"] == project_identity
    assert published["odbpp"]["artifact_path"] == "board/board-odb.zip"
    assert published["mechanical_review"]["artifact_path"] == "board/board.glb"
    assert published["coverage_comparison"]["gerber_jobset_artifact_count"] == 1
    assert published["coverage_comparison"]["ipc2581"] == "not-generated-by-bounded-review-oracle"
    assert published["coverage_comparison"]["step"] == "not-generated-by-bounded-review-oracle"
    proof = ManufacturingExportEvidence.model_validate(published["manufacturing_export_evidence"])
    assert proof.artifact_kinds == ["odbpp", "mechanical_review"]
    assert proof.blocked is False
    assert any("byte-for-byte" in warning.lower() for warning in proof.warnings)
    index = target / "board" / "index.html"
    assert index.is_file()
    review_html = index.read_text(encoding="utf-8")
    assert "Byte-for-byte export identity is not guaranteed" in review_html
    assert "run-bound integrity evidence" in review_html

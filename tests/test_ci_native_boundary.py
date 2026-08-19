"""Tests for installed-wheel Rust/PyO3 boundary evidence."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ci_native_boundary


class _FakeCore:
    __file__ = "/opt/native-site/zaptrace/_core.test.so"

    @staticmethod
    def place_components(n, width, height, connections, spacing):
        if width != width:
            raise ValueError("width_mm must be finite")
        if n > 1000:
            raise ValueError(f"components count {n} exceeds supported maximum 1000")
        if len(connections) > 10000:
            raise ValueError(f"placement_connections count {len(connections)} exceeds supported maximum 10000")
        if any(a >= n or b >= n for a, b in connections):
            raise ValueError("connection index out of bounds")
        return [(25.0 + index, 40.0) for index in range(n)]

    @staticmethod
    def route_mst(points):
        if len(points) > 2000:
            raise ValueError(f"mst_points count {len(points)} exceeds supported maximum 2000")
        if any(not (x == x and y == y) for x, y in points):
            raise ValueError("point coordinate must be finite")
        if len(points) < 2:
            return []
        return [(0.0, 0.0, 1.0, 0.0), (1.0, 0.0, 1.0, 1.0)]

    @staticmethod
    def route_shove(connections, obstacles, clearance):
        if clearance < 0:
            raise ValueError("clearance must be non-negative")
        if len(connections) > 10000:
            raise ValueError(f"shove_connections count {len(connections)} exceeds supported maximum 10000")
        if len(obstacles) > 2000:
            raise ValueError(f"shove_obstacles count {len(obstacles)} exceeds supported maximum 2000")
        if any(not math.isfinite(y2 + clearance) for _, _, _, y2 in obstacles):
            raise ValueError("detour_y must be finite")
        return [("N", "direct-l-path", True, [(0.0, 0.0, 1.0, 0.0)])]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "zaptrace_core").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        '[project]\nname = "zaptrace"\nversion = "0.3.1.dev0"\n',
        encoding="utf-8",
    )
    (root / "zaptrace_core/Cargo.toml").write_text(
        '[package]\nname = "zaptrace-core"\nversion = "0.3.1-dev.0"\n',
        encoding="utf-8",
    )
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Native Evidence Tests")
    _git(root, "config", "user.email", "native-tests@example.com")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "source")
    return root


def test_load_native_core_fails_when_extension_is_missing(monkeypatch) -> None:
    def missing(_name: str):
        raise ModuleNotFoundError("zaptrace._core")

    monkeypatch.setattr(ci_native_boundary.importlib, "import_module", missing)

    with pytest.raises(ci_native_boundary.NativeBoundaryError, match="not installed"):
        ci_native_boundary.load_native_core()


def test_build_report_records_identity_target_hashes_checks_and_limits(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_root = _source_root(tmp_path)
    (source_root / ".gitignore").write_text("native-dist/\n", encoding="utf-8")
    _git(source_root, "add", ".gitignore")
    _git(source_root, "commit", "-qm", "ignore build outputs")
    native_dist = source_root / "native-dist"
    native_dist.mkdir()
    (native_dist / "native.whl").write_bytes(b"ignored build artifact")
    wheel = tmp_path / "zaptrace-0.3.1.dev0-cp312-test.whl"
    wheel.write_bytes(b"wheel-fixture")
    monkeypatch.setattr(ci_native_boundary.metadata, "version", lambda _name: "0.3.1.dev0")

    report = ci_native_boundary.build_report(
        core=_FakeCore(),
        wheel=wheel,
        source_root=source_root,
        target="x86_64-unknown-linux-gnu",
    )

    assert report["schema_version"] == 1
    assert report["status"] == "pass"
    assert report["wheel"]["sha256"] == hashlib.sha256(b"wheel-fixture").hexdigest()
    assert report["source"] == {
        "commit": _git(source_root, "rev-parse", "HEAD"),
        "dirty": False,
        "ref": _git(source_root, "symbolic-ref", "HEAD"),
    }
    assert report["versions"] == {
        "installed_package": "0.3.1.dev0",
        "python_source": "0.3.1.dev0",
        "rust_crate": "0.3.1-dev.0",
    }
    assert report["runtime"]["target"] == "x86_64-unknown-linux-gnu"
    assert report["runtime"]["python_version"]
    assert report["runtime"]["system"]
    assert report["runtime"]["machine"]
    assert report["native_module"]["exported_functions"] == [
        "place_components",
        "route_mst",
        "route_shove",
    ]
    assert report["limits"] == {
        "max_components": 1000,
        "max_mst_points": 2000,
        "max_placement_connections": 10000,
        "max_shove_connections": 10000,
        "max_shove_obstacles": 2000,
    }
    assert report["process_survived_rejections"] is True
    assert all(check["status"] == "pass" for check in report["checks"])
    assert any(check["name"] == "invalid-values" for check in report["checks"])
    assert any(check["name"] == "all-resource-limits" for check in report["checks"])
    assert len(report["determinism"]["placement_sha256"]) == 64
    assert len(report["determinism"]["routing_sha256"]) == 64
    assert len(report["determinism"]["shove_sha256"]) == 64
    assert len(report["evidence_digest"]) == 64


def test_report_digest_is_deterministic(tmp_path: Path, monkeypatch) -> None:
    source_root = _source_root(tmp_path)
    wheel = tmp_path / "native.whl"
    wheel.write_bytes(b"same-wheel")
    monkeypatch.setattr(ci_native_boundary.metadata, "version", lambda _name: "0.3.1.dev0")

    first = ci_native_boundary.build_report(_FakeCore(), wheel, source_root, "test-target")
    second = ci_native_boundary.build_report(_FakeCore(), wheel, source_root, "test-target")

    assert first == second


def test_source_tree_extension_is_rejected_when_wheel_is_claimed(tmp_path: Path) -> None:
    source_root = _source_root(tmp_path)
    extension = source_root / "zaptrace" / "_core.so"
    extension.parent.mkdir(parents=True)
    extension.write_bytes(b"native")
    wheel = tmp_path / "native.whl"
    wheel.write_bytes(b"wheel")
    core = SimpleNamespace(__file__=str(extension))

    with pytest.raises(ci_native_boundary.NativeBoundaryError, match="source tree"):
        ci_native_boundary.build_report(core, wheel, source_root)


def test_dirty_source_fails_report(tmp_path: Path, monkeypatch) -> None:
    source_root = _source_root(tmp_path)
    wheel = tmp_path / "native.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(ci_native_boundary.metadata, "version", lambda _name: "0.3.1.dev0")
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "zaptrace"\nversion = "0.3.1.dev0"\n# dirty\n',
        encoding="utf-8",
    )

    report = ci_native_boundary.build_report(_FakeCore(), wheel, source_root)

    assert report["source"]["dirty"] is True
    assert report["status"] == "fail"
    assert any(check["name"] == "source-clean" and check["status"] == "fail" for check in report["checks"])


def test_version_drift_fails_report(tmp_path: Path, monkeypatch) -> None:
    source_root = _source_root(tmp_path)
    wheel = tmp_path / "native.whl"
    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(ci_native_boundary.metadata, "version", lambda _name: "9.9.9")

    report = ci_native_boundary.build_report(_FakeCore(), wheel, source_root)

    assert report["status"] == "fail"
    assert any(check["name"] == "version-consistency" and check["status"] == "fail" for check in report["checks"])


def test_cli_writes_json_and_markdown(tmp_path: Path, monkeypatch) -> None:
    source_root = _source_root(tmp_path)
    wheel = tmp_path / "native.whl"
    wheel.write_bytes(b"wheel")
    output = tmp_path / "native-boundary.json"
    markdown = tmp_path / "native-boundary.md"
    monkeypatch.setattr(ci_native_boundary, "load_native_core", lambda: _FakeCore())
    monkeypatch.setattr(ci_native_boundary.metadata, "version", lambda _name: "0.3.1.dev0")

    code = ci_native_boundary.main(
        [
            "--wheel",
            str(wheel),
            "--source-root",
            str(source_root),
            "--target",
            "test-target",
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"
    assert "Native Boundary Evidence" in markdown.read_text(encoding="utf-8")


def test_strict_exit_fails_closed() -> None:
    assert ci_native_boundary.exit_code({"status": "pass"}, strict=True) == 0
    assert ci_native_boundary.exit_code({"status": "fail"}, strict=True) == 1
    assert ci_native_boundary.exit_code({"status": "fail"}, strict=False) == 0


def test_native_boundary_reads_registry_distribution_metadata_name(tmp_path: Path, monkeypatch) -> None:
    source_root = _source_root(tmp_path)
    requested: list[str] = []

    def _version(name: str) -> str:
        requested.append(name)
        return "0.3.1.dev0"

    monkeypatch.setattr(ci_native_boundary.metadata, "version", _version)

    versions = ci_native_boundary._versions(source_root)

    assert requested == ["zaptrace-eda"]
    assert versions["installed_package"] == "0.3.1.dev0"

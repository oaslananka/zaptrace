from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import ci_package_inventory


def _wheel(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


def _sdist(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


def test_archive_members_reads_wheel_and_sdist(tmp_path: Path) -> None:
    wheel = tmp_path / "zaptrace-0.3.0-py3-none-any.whl"
    sdist = tmp_path / "zaptrace-0.3.0.tar.gz"
    _wheel(wheel, {"zaptrace/__init__.py": b""})
    _sdist(sdist, {"zaptrace-0.3.0/zaptrace/__init__.py": b""})

    assert ci_package_inventory.archive_members(wheel) == ("zaptrace/__init__.py",)
    assert ci_package_inventory.archive_members(sdist) == ("zaptrace-0.3.0/zaptrace/__init__.py",)


def test_validate_members_rejects_debug_build_cache_and_traversal() -> None:
    errors = ci_package_inventory.validate_members(
        [
            "zaptrace/core.pdb",
            "zaptrace/__pycache__/core.pyc",
            "build/generated.txt",
            "../escape.txt",
            "/absolute.txt",
        ]
    )

    assert any("core.pdb" in error and "debug/build extension" in error for error in errors)
    assert any("__pycache__" in error and "generated directory" in error for error in errors)
    assert any("build/generated.txt" in error and "generated directory" in error for error in errors)
    assert any("../escape.txt" in error and "unsafe archive path" in error for error in errors)
    assert any("/absolute.txt" in error and "unsafe archive path" in error for error in errors)


def test_validate_members_allows_expected_python_and_native_runtime_files() -> None:
    assert (
        ci_package_inventory.validate_members(
            [
                "zaptrace/__init__.py",
                "zaptrace/_core.cpython-312-x86_64-linux-gnu.so",
                "zaptrace/_core.cp312-win_amd64.pyd",
                "zaptrace-0.3.0.dist-info/METADATA",
                "data/fab_profiles/jlcpcb-2layer.yaml",
            ]
        )
        == []
    )


def test_validate_members_rejects_unexpected_native_library() -> None:
    errors = ci_package_inventory.validate_members(["zaptrace/vendor/libhelper.so"])
    assert errors == ["zaptrace/vendor/libhelper.so: unexpected native library in package"]


def test_inspect_dist_requires_wheel_and_sdist_and_reports_errors(tmp_path: Path) -> None:
    wheel = tmp_path / "zaptrace-0.3.0-py3-none-any.whl"
    sdist = tmp_path / "zaptrace-0.3.0.tar.gz"
    _wheel(wheel, {"zaptrace/__init__.py": b"", "zaptrace/core.pdb": b"bad"})
    _sdist(sdist, {"zaptrace-0.3.0/zaptrace/__init__.py": b""})

    report = ci_package_inventory.inspect_dist(tmp_path)

    assert report["passed"] is False
    assert report["archive_count"] == 2
    assert any("core.pdb" in error for error in report["errors"])


def test_inspect_dist_rejects_missing_distribution_kind(tmp_path: Path) -> None:
    _wheel(tmp_path / "zaptrace-0.3.0-py3-none-any.whl", {"zaptrace/__init__.py": b""})

    with pytest.raises(ValueError, match="source distribution"):
        ci_package_inventory.inspect_dist(tmp_path)


def test_inspect_dist_accepts_registry_distribution_filenames(tmp_path: Path) -> None:
    wheel = tmp_path / "zaptrace_eda-0.3.2.dev0-py3-none-any.whl"
    sdist = tmp_path / "zaptrace_eda-0.3.2.dev0.tar.gz"
    _wheel(wheel, {"zaptrace/__init__.py": b""})
    _sdist(sdist, {"zaptrace_eda-0.3.2.dev0/zaptrace/__init__.py": b""})

    report = ci_package_inventory.inspect_dist(tmp_path)

    assert report["passed"] is True
    assert [archive["path"] for archive in report["archives"]] == [wheel.name, sdist.name]

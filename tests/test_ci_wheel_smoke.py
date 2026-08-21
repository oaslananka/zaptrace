from __future__ import annotations

from pathlib import Path

from scripts import ci_wheel_smoke


def test_select_wheel_accepts_registry_distribution_filename(tmp_path: Path) -> None:
    wheel = tmp_path / "zaptrace_eda-0.3.2.dev0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")

    assert ci_wheel_smoke.select_wheel(tmp_path) == wheel


def test_select_wheel_accepts_native_platform_wheel(tmp_path: Path) -> None:
    wheel = tmp_path / "zaptrace_eda-0.3.4.dev0-cp313-cp313-manylinux_2_35_x86_64.whl"
    wheel.write_bytes(b"wheel")

    assert ci_wheel_smoke.select_wheel(tmp_path) == wheel


def test_select_wheel_raises_when_no_wheels(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(FileNotFoundError, match="no ZapTrace wheel found"):
        ci_wheel_smoke.select_wheel(tmp_path)

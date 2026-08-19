from __future__ import annotations

from pathlib import Path

from scripts import ci_wheel_smoke


def test_select_wheel_accepts_registry_distribution_filename(tmp_path: Path) -> None:
    wheel = tmp_path / "zaptrace_eda-0.3.2.dev0-py3-none-any.whl"
    wheel.write_bytes(b"wheel")

    assert ci_wheel_smoke.select_wheel(tmp_path) == wheel

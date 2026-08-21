"""Install the built wheel into a clean environment and verify runtime assets."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_DISTRIBUTION_STEMS = ("zaptrace_eda", "zaptrace")


def run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, check=True)


def venv_python(venv: Path) -> Path:
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


def select_wheel(dist_dir: Path) -> Path:
    wheels = sorted({path for stem in _DISTRIBUTION_STEMS for path in dist_dir.glob(f"{stem}-*.whl")})
    if not wheels:
        raise FileNotFoundError(f"no ZapTrace wheel found in {dist_dir}")
    if len(wheels) > 1:
        print(f"INFO: multiple wheels found; testing {wheels[0].name}")
    return wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a clean installed-wheel smoke test")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument(
        "--expected-native",
        choices=("required", "absent", "optional"),
        default="optional",
        help="Enforce presence or absence of the native Rust extension",
    )
    args = parser.parse_args()

    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("uv is required for the wheel smoke test")

    wheel = select_wheel(args.dist_dir)
    with tempfile.TemporaryDirectory(prefix="zaptrace-wheel-smoke-") as tmp:
        venv = Path(tmp) / ".venv"
        run([uv, "venv", str(venv)], cwd=ROOT)
        python = venv_python(venv)
        run([uv, "pip", "install", "--python", str(python), str(wheel)], cwd=ROOT)
        env = dict(os.environ)
        env["ZAPTRACE_EXPECTED_NATIVE"] = args.expected_native
        run([str(python), "-c", SMOKE], cwd=Path(tmp), env=env)
    return 0


SMOKE = r"""
import importlib.util
import os
from pathlib import Path
import tempfile

import zaptrace
import zaptrace.kicad

from zaptrace.ee.footprint_vendor import resolve_vendored_footprint
from zaptrace.fab import get_builtin_profile_names
from zaptrace.library.loader import LIBRARY_ROOT, LibraryLoader
from zaptrace.synthesis.engine import list_templates
from zaptrace.synthesis.fab import synthesize_to_manufacturing

expected_native = os.environ.get("ZAPTRACE_EXPECTED_NATIVE", "optional")
native_found = importlib.util.find_spec("zaptrace._core") is not None
if expected_native == "required" and not native_found:
    raise AssertionError("zaptrace._core native extension is required but missing from wheel")
if expected_native == "absent" and native_found:
    raise AssertionError("zaptrace._core native extension is absent but found in wheel")

loader = LibraryLoader()
library = loader.load_all()
assert LIBRARY_ROOT.exists(), f"library root missing: {LIBRARY_ROOT}"
assert len(library) >= 80, f"component library unexpectedly small: {len(library)}"
loader.get("usb-c-16p")
assert len(list_templates()) >= 5, "synthesis templates missing"
assert "jlcpcb-2layer" in get_builtin_profile_names(), "fab profiles missing"
assert resolve_vendored_footprint("BME280-LGA8") is not None, "vendored KiCad footprint missing"

with tempfile.TemporaryDirectory(prefix="zaptrace-fab-smoke-") as out:
    result = synthesize_to_manufacturing("ESP32-C3 USB-C 3.3V I2C temperature sensor", Path(out))
    assert result.component_count > 0, "manufacturing synthesis emitted no components"
    assert result.artifacts, "manufacturing synthesis emitted no artifacts"

print(f"OK: ZapTrace {zaptrace.__version__} clean wheel smoke passed (native={native_found})")
"""


if __name__ == "__main__":
    raise SystemExit(main())

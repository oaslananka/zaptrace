"""Tests for vendored (verified KiCad) footprint resolution."""

from __future__ import annotations

from zaptrace.ee.footprint_proof import file_sha256
from zaptrace.ee.footprint_vendor import VENDOR_FOOTPRINTS, resolve_vendored_footprint, vendored_footprint_path
from zaptrace.kicad.importer import load_kicad_footprint
from zaptrace.synthesis.footprint_resolver import resolve_footprints
from zaptrace.synthesis.repair import synthesize_and_repair


class TestVendorRegistry:
    def test_every_registered_file_exists_and_parses(self) -> None:
        # Each registry entry must resolve to a real, parseable land pattern with pads.
        for name in VENDOR_FOOTPRINTS:
            fp = resolve_vendored_footprint(name)
            assert fp is not None, f"{name} did not resolve"
            assert fp.pads, f"{name} has no pads"
            assert fp.courtyard != (0.0, 0.0), f"{name} has no courtyard extent"

    def test_release_critical_vendor_sources_have_pinned_hashes(self) -> None:
        expected = {
            "ESP32-WROOM-32": "62127c6680f44ce358890322adc2c764c4120fc0af2f87b636378de5a34b08b7",
            "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal": (
                "db924af7ac6b9ed7b16df1f598a56268c6a32ec33583557b6e5d8aa5056e3b2c"
            ),
        }
        for name, digest in expected.items():
            path = vendored_footprint_path(name)
            assert path is not None
            assert file_sha256(path) == digest

    def test_unknown_name_returns_none(self) -> None:
        assert resolve_vendored_footprint("NOT-A-REAL-FOOTPRINT") is None

    def test_returns_fresh_copy_each_call(self) -> None:
        a = resolve_vendored_footprint("BME280-LGA8")
        b = resolve_vendored_footprint("BME280-LGA8")
        assert a is not None
        assert b is not None
        assert a is not b  # distinct objects, safe to mutate independently
        a.pads.clear()
        assert b.pads, "mutating one copy must not affect another"

    def test_known_package_pad_counts(self) -> None:
        # Sanity-check the geometry actually came from the right package.
        assert len(resolve_vendored_footprint("BME280-LGA8").pads) == 8  # type: ignore[union-attr]
        assert len(resolve_vendored_footprint("SHT31-DIS-DFN8").pads) == 9  # 8 + thermal EP  # type: ignore[union-attr]
        assert len(resolve_vendored_footprint("ESP32-WROOM-32").pads) == 60  # type: ignore[union-attr]
        assert (
            len(resolve_vendored_footprint("USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal").pads) == 20  # type: ignore[union-attr]
        )


class TestFootprintImporter:
    def test_courtyard_extent_collects_line_rect_and_polygon_points(self, tmp_path: object) -> None:
        from pathlib import Path

        footprint = Path(str(tmp_path)) / "mixed.kicad_mod"
        footprint.write_text(
            """(footprint Mixed
  (fp_line (start -1 -2) (end 3 4) (layer F.CrtYd))
  (fp_rect (start -2 -1) (end 2 5) (layer F.CrtYd))
  (fp_poly (pts (xy -3 0) (xy 1 6) (xy 4 2)) (layer F.CrtYd))
  (fp_line (start -100 -100) (end 100 100) (layer F.SilkS))
  (pad 1 thru_hole circle (at 0 0) (size 1 1) (drill 0.5) (layers *.Cu *.Mask))
)
""",
            encoding="utf-8",
        )

        loaded = load_kicad_footprint(footprint)

        assert loaded is not None
        assert loaded.courtyard == (7.0, 8.0)

    def test_courtyard_extent_falls_back_to_padded_pad_bbox(self, tmp_path: object) -> None:
        from pathlib import Path

        footprint = Path(str(tmp_path)) / "pad-only.kicad_mod"
        footprint.write_text(
            """(footprint PadOnly
  (pad 1 thru_hole circle (at -1 2) (size 2 4) (drill 0.5) (layers *.Cu *.Mask))
  (pad 2 thru_hole circle (at 4 -2) (size 1 2) (drill 0.5) (layers *.Cu *.Mask))
)
""",
            encoding="utf-8",
        )

        loaded = load_kicad_footprint(footprint)

        assert loaded is not None
        assert loaded.courtyard == (7.0, 7.5)

    def test_load_nonexistent_returns_none(self, tmp_path: object) -> None:
        from pathlib import Path

        bogus = Path(str(tmp_path)) / "missing.kicad_mod"
        bogus.write_text("(module foo)", encoding="utf-8")
        assert load_kicad_footprint(bogus) is None  # not a footprint form


class TestResolverIntegration:
    def test_esp32_module_resolves_via_vendor(self) -> None:
        out = synthesize_and_repair("ESP32-C3 wifi board, I2C BME280")
        result = resolve_footprints(out["design"])
        assert result.fully_resolved, f"unresolved: {result.unresolved}"
        # The ESP32 module and the BME280 both come from vendored land patterns.
        u1 = next(c for c in out["design"].components.values() if c.footprint == "ESP32-C3-MINI-1")
        assert u1.footprint_def is not None
        assert u1.footprint_def.pads

    def test_ethernet_rj45_resolves_via_vendor(self) -> None:
        out = synthesize_and_repair("industrial board, 12V input, 3.3V rail, I2C, ethernet")
        result = resolve_footprints(out["design"])
        assert result.fully_resolved, f"unresolved: {result.unresolved}"

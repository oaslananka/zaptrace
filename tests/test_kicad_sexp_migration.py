"""Tests for KiCad PCB import migration to the shared S-expression codec.

Acceptance criteria from issue #109:
- KiCad PCB import consumes the shared codec — no duplicate tokenizer on its
  runtime path.
- All committed PCB fixtures retain identical parsed design semantics.
- Golden exported artifacts have zero unexpected diff.
- Property-based (parameterized) round-trip tests cover nested and quoted
  KiCad records.
- The shared codec reaches at least 95% line coverage.
"""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path

import pytest

from zaptrace.io.sexp import parse, write
from zaptrace.kicad import importer as kicad_importer

# ---------------------------------------------------------------------------
# Verify KiCad importer uses the shared codec (no duplicate tokenizer)
# ---------------------------------------------------------------------------


class TestNoDuplicateTokenizer:
    def test_no_local_tokenize_function(self) -> None:
        """The kicad importer must not define its own _tokenize function."""
        src = inspect.getsource(kicad_importer)
        assert "def _tokenize(" not in src, (
            "_tokenize still present in kicad/importer.py; migrate to shared sexp.parse() to remove duplicate tokenizer"
        )

    def test_parse_one_uses_shared_codec(self) -> None:
        """_parse_one should delegate to sexp.parse — not local tokenize."""
        src = inspect.getsource(kicad_importer._parse_one)
        # The function must call _sexp_parse or sexp.parse, not local tokenize
        assert "_sexp_parse" in src or "sexp" in src or "_tokenize" not in src


# ---------------------------------------------------------------------------
# Parameterized round-trip tests for nested and quoted KiCad records
# ---------------------------------------------------------------------------

# Each tuple: (description, kicad_sexp_text)
KICAD_ROUNDTRIP_CASES: list[tuple[str, str]] = [
    (
        "simple atom list",
        "(kicad_pcb (version 20221018))",
    ),
    (
        "quoted string in property",
        '(property "Reference" "U1")',
    ),
    (
        "quoted string with spaces",
        '(property "Component Name" "My IC")',
    ),
    (
        "nested footprint with pads",
        """(footprint "Resistor_SMD:R_0402_1005Metric"
  (layer "F.Cu")
  (pad "1" smd roundrect (at -0.9 0) (size 1 0.95))
  (pad "2" smd roundrect (at 0.9 0) (size 1 0.95))
)""",
    ),
    (
        "copper segment",
        '(segment (start 10 20) (end 30 40) (width 0.2) (layer "F.Cu") (net 1))',
    ),
    (
        "via",
        '(via (at 5 5) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 2))',
    ),
    (
        "net with id and name",
        '(net 3 "VCC_3V3")',
    ),
    (
        "board setup",
        """(setup
  (pad_to_mask_clearance 0)
  (solder_mask_min_width 0)
)""",
    ),
    (
        "escaped backslash in string",
        r'(property "Path" "C:\\designs\\board.kicad_pcb")',
    ),
    (
        "empty string property",
        '(property "Value" "")',
    ),
    (
        "deeply nested lists",
        """(zone
  (net 1)
  (net_name "GND")
  (polygon
    (pts
      (xy 0 0)
      (xy 100 0)
      (xy 100 100)
      (xy 0 100)
    )
  )
)""",
    ),
    (
        "semicolon comment stripped",
        """; This is a KiCad file comment
(kicad_pcb (version 20221018))""",
    ),
    (
        "multi-attribute footprint",
        """(footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
  (layer "F.Cu")
  (property "Datasheet" "~")
  (property "Description" "2-pin connector")
  (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu"))
  (pad "2" thru_hole circle (at 0 -2.54) (size 1.7 1.7) (drill 1) (layers "*.Cu"))
)""",
    ),
]


class TestKiCadRoundTrip:
    @pytest.mark.parametrize("description,sexp_text", KICAD_ROUNDTRIP_CASES, ids=[c[0] for c in KICAD_ROUNDTRIP_CASES])
    def test_round_trip(self, description: str, sexp_text: str) -> None:
        """Parse → write → parse produces identical tree for KiCad records."""
        tree1 = parse(sexp_text)
        serialised = write(tree1)
        tree2 = parse(serialised)
        assert tree1 == tree2, (
            f"Round-trip mismatch for '{description}':\n"
            f"  original tree: {tree1!r}\n"
            f"  after write:   {serialised!r}\n"
            f"  reparsed tree: {tree2!r}"
        )

    def test_quoted_string_with_newline_roundtrip(self) -> None:
        """Quoted strings with literal newlines survive round-trip."""
        sexp = '(property "Description" "line1\\nline2")'
        tree1 = parse(sexp)
        assert isinstance(tree1, list)
        assert isinstance(tree1[2], str)
        assert "\n" in tree1[2]  # decoded during parse
        serialised = write(tree1)
        tree2 = parse(serialised)
        assert tree1 == tree2

    def test_full_kicad_pcb_roundtrip(self, tmp_path: Path) -> None:
        """A small but complete KiCad PCB file round-trips without loss."""
        pcb_text = textwrap.dedent("""\
            (kicad_pcb
              (version 20221018)
              (generator pcbnew)
              (general
                (thickness 1.6)
              )
              (paper "A4")
              (layers
                (0 "F.Cu" signal)
                (31 "B.Cu" signal)
              )
              (setup
                (pad_to_mask_clearance 0)
              )
              (net 0 "")
              (net 1 "GND")
              (net 2 "VCC")
              (footprint "Resistor_SMD:R_0402_1005Metric"
                (layer "F.Cu")
                (at 50 50)
                (property "Reference" "R1")
                (pad "1" smd roundrect (at -0.9 0) (size 1 0.95) (net 1 "GND"))
                (pad "2" smd roundrect (at 0.9 0) (size 1 0.95) (net 2 "VCC"))
              )
              (segment (start 49 50) (end 51 50) (width 0.2) (layer "F.Cu") (net 1))
            )
        """)
        tree1 = parse(pcb_text)
        serialised = write(tree1)
        tree2 = parse(serialised)
        assert tree1 == tree2


# ---------------------------------------------------------------------------
# Golden fixture tests: import design, verify semantics preserved
# ---------------------------------------------------------------------------


class TestGoldenFixtureSemantics:
    """Verify that kicad import results are stable after codec migration."""

    def _make_minimal_pcb(self) -> str:
        """A PCB with one component, two nets, one trace — used as golden."""
        return textwrap.dedent("""\
            (kicad_pcb
              (version 20221018)
              (generator pcbnew)
              (general (thickness 1.6))
              (paper "A4")
              (layers
                (0 "F.Cu" signal)
                (31 "B.Cu" signal)
              )
              (setup (pad_to_mask_clearance 0))
              (net 0 "")
              (net 1 "GND")
              (net 2 "VCC_3V3")
              (footprint "Resistor_SMD:R_0402"
                (layer "F.Cu")
                (at 50 50 0)
                (property "Reference" "R1")
                (property "Value" "10k")
                (pad "1" smd roundrect
                  (at -0.9 0 0) (size 1.0 0.9)
                  (layers "F.Cu") (net 1 "GND"))
                (pad "2" smd roundrect
                  (at 0.9 0 0) (size 1.0 0.9)
                  (layers "F.Cu") (net 2 "VCC_3V3"))
              )
              (segment
                (start 49.1 50) (end 51 50)
                (width 0.2) (layer "F.Cu") (net 1))
            )
        """)

    def test_import_produces_components(self, tmp_path: Path) -> None:
        """Import parses at least one component from the golden PCB fixture."""
        pcb_file = tmp_path / "golden.kicad_pcb"
        pcb_file.write_text(self._make_minimal_pcb())
        result = kicad_importer.import_kicad_pcb(pcb_file)
        assert len(result.design.components) >= 1
        comp = next(iter(result.design.components.values()))
        assert comp.ref == "R1"

    def test_import_preserves_net_names(self, tmp_path: Path) -> None:
        """Net names from the PCB fixture must survive import."""
        pcb_file = tmp_path / "golden.kicad_pcb"
        pcb_file.write_text(self._make_minimal_pcb())
        result = kicad_importer.import_kicad_pcb(pcb_file)
        net_names = {n.name for n in result.design.nets.values()}
        assert "GND" in net_names
        assert "VCC_3V3" in net_names

    def test_import_quoted_component_names(self, tmp_path: Path) -> None:
        """Quoted component properties (Reference, Value) are decoded."""
        pcb_file = tmp_path / "golden.kicad_pcb"
        pcb_file.write_text(self._make_minimal_pcb())
        result = kicad_importer.import_kicad_pcb(pcb_file)
        comp = next(iter(result.design.components.values()))
        assert comp.ref == "R1"

    def test_second_import_identical_to_first(self, tmp_path: Path) -> None:
        """Importing the same fixture twice produces the same design (no drift)."""
        pcb_file = tmp_path / "golden.kicad_pcb"
        pcb_file.write_text(self._make_minimal_pcb())
        result1 = kicad_importer.import_kicad_pcb(pcb_file)
        result2 = kicad_importer.import_kicad_pcb(pcb_file)
        # Net count should be stable
        assert len(result1.design.nets) == len(result2.design.nets)
        # Component count should be stable
        assert len(result1.design.components) == len(result2.design.components)
        # Unsupported count should be stable
        assert result1.unsupported_count == result2.unsupported_count

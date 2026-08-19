from pathlib import Path

import pytest

from zaptrace.core.models import RouteResult
from zaptrace.io.ses import parse_ses


def test_parse_ses_valid(tmp_path: Path):
    ses_content = """(session test
      (resolution um 10)
      (placement
        (component U1
          (place U1 -1.5 2.5 front 0)
        )
      )
      (routes
        (library_out
          (padstack Via[0-1]_800:400_um
            (shape (circle F.Cu 800.0))
            (shape (circle B.Cu 800.0))
            (attach off)
          )
        )
        (network_out
          (net VCC
            (wire (path F.Cu 2500.0 0.0 0.0 10000.0 10000.0))
            (wire (path B.Cu 2500.0 10000.0 10000.0 20000.0 20000.0))
            (via Via[0-1]_800:400_um 10000.0 10000.0)
          )
          (net GND
            (wire (path F.Cu 2000.0 50000.0 50000.0 60000.0 60000.0))
          )
        )
      )
    )"""
    ses_file = tmp_path / "valid.ses"
    ses_file.write_text(ses_content)

    result = parse_ses(ses_file)

    assert isinstance(result, RouteResult)
    assert result.net_count == 2
    assert result.routed_net_count == 2

    # Check trace segments. VCC has 2 traces + 1 via (represented as segment), GND has 1 trace. Total = 4
    assert len(result.traces) == 4

    traces = [t for t in result.traces if not t.via]
    assert len(traces) == 3

    # Scale: um 10 -> factor is 1/10000.0 for mm
    # 2500 -> 0.25 mm, 10000 -> 1.0 mm, 20000 -> 2.0 mm

    vcc_f_cu = next((t for t in traces if t.net_id == "VCC" and t.layer == "F.Cu"), None)
    assert vcc_f_cu is not None
    assert vcc_f_cu.width == 0.25
    assert vcc_f_cu.start == (0.0, 0.0)
    assert vcc_f_cu.end == (1.0, 1.0)

    # Check Vias
    assert len(result.vias) == 1
    via_x, via_y, via_diam, via_hole = result.vias[0]
    assert via_x == 1.0
    assert via_y == 1.0
    assert via_diam == 0.8
    assert via_hole == 0.4

    assert set(result.layers_used) == {"F.Cu", "B.Cu"}


def test_parse_ses_malformed_syntax(tmp_path: Path):
    ses_content = ")"
    ses_file = tmp_path / "malformed.ses"
    ses_file.write_text(ses_content)

    with pytest.raises(ValueError, match="Unexpected '\\)'|Malformed SES file"):
        parse_ses(ses_file)


def test_parse_ses_missing_file():
    with pytest.raises(ValueError, match="Failed to read SES file"):
        parse_ses("nonexistent_file.ses")


def test_parse_ses_malformed_path_or_wire(tmp_path: Path):
    # Tests that bad datatypes in the path node are gracefully skipped rather than crashing
    ses_content = """(session test
      (routes
        (network_out
          (net VCC
            (wire (path F.Cu INVALID 0.0 0.0 1.0 1.0))
            (via InvalidVia INVALID 1.0)
          )
        )
      )
    )"""
    ses_file = tmp_path / "bad_data.ses"
    ses_file.write_text(ses_content)

    result = parse_ses(ses_file)
    # The parser ignores the bad trace and via gracefully without crashing
    assert len(result.traces) == 0
    assert len(result.vias) == 0

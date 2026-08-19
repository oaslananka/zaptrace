"""Regression coverage for stable EasyEDA Pro archive member names."""

import io
import zipfile

from zaptrace.core.models import Design, DesignMeta
from zaptrace.eda.easyeda_pro import read_easyeda_pro_zip, write_easyeda_pro_zip


def test_easyeda_archive_member_names_round_trip() -> None:
    payload, _report = write_easyeda_pro_zip(Design(meta=DesignMeta(name="ArchiveNames")))

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "project.json",
            "schematic.jsonl",
            "pcb.jsonl",
        }

    project = read_easyeda_pro_zip(payload)
    assert project.project_name == "ArchiveNames"

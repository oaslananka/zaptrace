"""Regression coverage for proof-pack metadata archive paths."""

import zipfile
from pathlib import Path

from zaptrace.proof.pack import ProofPack


def test_proof_bundle_writes_each_metadata_record_once(tmp_path: Path) -> None:
    (tmp_path / "design.yaml").write_text(
        "meta:\n  name: ArchivePaths\ncomponents: {}\n",
        encoding="utf-8",
    )
    proof_path = tmp_path / "proof.yaml"
    proof_path.write_text(
        "version: '1.0'\nname: archive-paths\ndesign_path: design.yaml\nchecks: []\n",
        encoding="utf-8",
    )

    pack = ProofPack.load(proof_path)
    pack.run()
    bundle = pack.bundle(tmp_path / "out")

    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()

    for metadata_path in ("manifest.json", "results.json", "stable_id.txt"):
        assert names.count(metadata_path) == 1

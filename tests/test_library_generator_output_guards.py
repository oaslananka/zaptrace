"""Library expansion must not redirect generated files outside the selected output tree."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import generate_library_expansion as generator


def _parts() -> list[tuple[str, str, dict]]:
    return [("passive", "demo_part", {"name": "Demo part", "value": "1k"})]


@pytest.mark.parametrize("alias", ["root", "category", "dangling_leaf"])
def test_rejects_indirect_output_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str) -> None:
    monkeypatch.setattr(generator, "collect_all_parts", _parts)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    (outside / "keep.txt").write_text("important")
    root = tmp_path / "library"
    if alias == "root":
        root.symlink_to(outside, target_is_directory=True)
    elif alias == "category":
        root.mkdir()
        (root / "passive").symlink_to(outside, target_is_directory=True)
    else:
        (root / "passive").mkdir(parents=True)
        (root / "passive" / "demo_part.yaml").symlink_to(outside / "new.yaml")
    with pytest.raises(ValueError, match="Unsafe library output"):
        generator.main(["--output-dir", str(root)])
    assert (outside / "keep.txt").read_text() == "important"
    assert not (outside / "new.yaml").exists()
    assert not (outside / "demo_part.yaml").exists()


@pytest.mark.parametrize(
    ("category", "part_id"),
    [
        ("../outside", "demo_part"),
        ("passive", "../../outside"),
        ("passive/name", "demo_part"),
        ("passive", "demo/part"),
    ],
)
def test_rejects_path_components_from_generated_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, category: str, part_id: str
) -> None:
    monkeypatch.setattr(generator, "collect_all_parts", lambda: [(category, part_id, {"name": "Untrusted"})])
    root = tmp_path / "library"
    with pytest.raises(ValueError, match="Unsafe library output"):
        generator.main(["--output-dir", str(root)])
    assert not (tmp_path / "outside" / "demo_part.yaml").exists()
    assert not (tmp_path / "outside.yaml").exists()


def test_valid_generated_file_is_exclusive_idempotent_and_dry_run_is_non_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generator, "collect_all_parts", _parts)
    root = tmp_path / "library"
    assert generator.main(["--output-dir", str(root), "--dry-run"]) == 0
    assert not root.exists()
    assert generator.main(["--output-dir", str(root)]) == 0
    output = root / "passive" / "demo_part.yaml"
    assert yaml.safe_load(output.read_text()) == {"name": "Demo part", "value": "1k"}
    before = output.read_bytes()
    assert generator.main(["--output-dir", str(root)]) == 0
    assert output.read_bytes() == before


def test_invalid_later_inventory_entry_prevents_partial_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generator,
        "collect_all_parts",
        lambda: _parts() + [("../outside", "bad_component", {"name": "Invalid"})],
    )
    root = tmp_path / "library"
    with pytest.raises(ValueError, match="Unsafe library output"):
        generator.main(["--output-dir", str(root)])
    assert not root.exists()


def test_existing_directory_at_output_file_is_not_silently_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generator, "collect_all_parts", _parts)
    output = tmp_path / "library" / "passive" / "demo_part.yaml"
    output.mkdir(parents=True)
    with pytest.raises(ValueError, match="Unsafe library output"):
        generator.main(["--output-dir", str(tmp_path / "library")])
    assert output.is_dir()

"""User-owned KiCad review export and explicit permanent deletion safety."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from review_studio_library import CONFIRM, delete_review, export_review, managed_paths
from review_studio_workspace import _append_project, _read_projects, render_workspace, workspace_html


def local_import(tmp_path: Path, *, name: str = "My confidential PCB") -> tuple[Path, str, str, Path, Path, Path]:
    workspace = tmp_path / "workspace"
    original = tmp_path / "private-user-boards" / "actual_board.kicad_pcb"
    original.parent.mkdir(exist_ok=True)
    original.write_bytes(b"(kicad_pcb real native source test)" + b"a" * 400)
    sha = hashlib.sha256(original.read_bytes()).hexdigest()
    run = uuid.uuid4().hex
    key = "my-confidential-pcb"
    output = workspace / "projects" / (key + "-" + sha[:12] + "-" + run)
    staging = workspace / "local-imports" / run
    output.mkdir(parents=True)
    staging.mkdir(parents=True)
    (staging / "source.kicad_pcb").write_bytes(original.read_bytes())
    (staging / "source.kicad_sch").write_text("(kicad_sch user-selected sheet)")
    (output / "index.html").write_text("<!doctype html><title>KiCad review</title>")
    (output / "REVIEW_REPORT.html").write_text("<!doctype html><title>Native DRC evidence</title>")
    (output / "native-drc.rpt").write_text("** Found 16 DRC violations **")
    (output / "evidence.json").write_text(
        json.dumps(
            {
                "source_sha256": sha,
                "board_name": "actual_board",
                "board": {"pads": [], "copper": [], "size": [64, 62]},
                "findings": [{"rule": "drill_out_of_range"}],
                "drc_state": "reported",
                "erc": {"state": "not_run", "count": 0},
                "project_settings": {},
            }
        )
    )
    _append_project(workspace, name, output)
    render_workspace(workspace)
    return workspace, key, sha, original, output, staging


def test_export_contains_originally_selected_kicad_and_native_drc_evidence(tmp_path: Path) -> None:
    workspace, key, sha, original, output, staged = local_import(tmp_path)
    archive = export_review(workspace, key, sha)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        members = set(z.namelist())
        assert "selected-input-copies/source.kicad_pcb" in members
        assert "selected-input-copies/source.kicad_sch" in members
        assert "review/evidence.json" in members
        assert "review/native-drc.rpt" in members
        assert z.read("selected-input-copies/source.kicad_pcb") == original.read_bytes()
        assert b"sensitive PCB" in z.read("README-LOCAL-BACKUP.txt")
        assert z.testzip() is None
    assert output.exists() and staged.exists()
    assert len(_read_projects(workspace)) == 1


def test_delete_needs_explicit_confirm_and_removes_only_local_copies(tmp_path: Path) -> None:
    workspace, key, sha, original, review, staged = local_import(tmp_path)
    old_content = original.read_bytes()
    with pytest.raises(ValueError, match="Explicit"):
        delete_review(workspace, key, sha, "DELETE")
    assert review.exists() and staged.exists()
    with pytest.raises(ValueError, match="checksum"):
        delete_review(workspace, key, "0" * 64, CONFIRM)
    with pytest.raises(ValueError, match="identification"):
        delete_review(workspace, "../outside", sha, CONFIRM)
    result = delete_review(workspace, key, sha, CONFIRM)
    assert result["state"] == "deleted"
    assert not review.exists() and not staged.exists()
    assert original.read_bytes() == old_content
    assert _read_projects(workspace) == []
    assert "No native KiCad boards yet" in (workspace / "index.html").read_text()
    assert not list(workspace.glob("**/source.kicad_pcb"))


def test_external_registered_source_never_deleted_or_unregistered(tmp_path: Path) -> None:
    workspace, key, sha, original, review, staged = local_import(tmp_path)
    external = tmp_path / "outside-research" / "review"
    external.mkdir(parents=True)
    for member in ("evidence.json", "index.html", "REVIEW_REPORT.html"):
        (external / member).write_bytes((review / member).read_bytes())
    _append_project(workspace, "Source registered outside Review Studio", external)
    with pytest.raises(ValueError, match="Only completed"):
        delete_review(workspace, "source-registered-outside-review-studio", sha, CONFIRM)
    with pytest.raises(ValueError, match="Only completed"):
        export_review(workspace, "source-registered-outside-review-studio", sha)
    assert external.exists() and (external / "evidence.json").is_file()
    assert len(_read_projects(workspace)) == 2
    delete_review(workspace, key, sha, CONFIRM)
    assert original.exists() and external.exists()
    assert len(_read_projects(workspace)) == 1
    assert "Source registered outside Review Studio" in (workspace / "index.html").read_text()


def test_export_rejects_staging_content_tampering_and_symlink(tmp_path: Path) -> None:
    workspace, key, sha, original, review, staging = local_import(tmp_path)
    (staging / "source.kicad_pcb").write_bytes(b"modified")
    with pytest.raises(ValueError, match="differ"):
        export_review(workspace, key, sha)
    (staging / "source.kicad_pcb").write_bytes(original.read_bytes())
    (staging / "secret.txt").symlink_to(original)
    with pytest.raises(ValueError, match="symbolic"):
        export_review(workspace, key, sha)
    assert managed_paths(workspace, review) is not None
    with pytest.raises(ValueError, match="Explicit"):
        delete_review(workspace, key, sha, "wrong")
    assert original.exists()


def test_directory_symlink_cannot_make_library_delete_other_user_source(tmp_path: Path) -> None:
    workspace, key, sha, original, review, staging = local_import(tmp_path)
    private = tmp_path / "private-user-boards"
    staging.rename(staging.parent / (staging.name + "-moved"))
    staging.symlink_to(private, target_is_directory=True)
    assert managed_paths(workspace, review) is None
    with pytest.raises(ValueError, match="Only completed"):
        delete_review(workspace, key, sha, CONFIRM)
    assert original.exists()


def test_library_html_actions_exist_only_for_app_owned_imports(tmp_path: Path) -> None:
    workspace, key, sha, original, review, staging = local_import(tmp_path)
    catalog = workspace_html(workspace, _read_projects(workspace))
    assert 'class="data-actions" hidden' in catalog
    assert 'class="backup-review"' in catalog and 'class="delete-review"' in catalog
    assert 'id="reviewDeleteDialog"' in catalog
    assert "Type <strong>DELETE</strong>" in catalog
    assert f'data-key="{key}"' in catalog and f'data-sha="{sha}"' in catalog
    other = tmp_path / "external"
    other.mkdir()
    for member in ("evidence.json", "index.html", "REVIEW_REPORT.html"):
        (other / member).write_bytes((review / member).read_bytes())
    _append_project(workspace, "Externally verified KiCad result", other)
    catalog = workspace_html(workspace, _read_projects(workspace))
    assert catalog.count('class="data-actions"') == 1


def test_restore_reads_only_native_kicad_inputs_and_discards_untrusted_rendered_html(tmp_path: Path) -> None:
    from review_studio_library import validate_restore_backup

    workspace, key, sha, original, review, staged = local_import(tmp_path)
    (staged / "source.kicad_sch").write_bytes(b"(kicad_sch " + b"x" * 200 + b")")
    (review / "index.html").write_text("<script>alert('a forged fab approved report')</script>")
    (review / "evidence.json").write_text((review / "evidence.json").read_text().replace('"reported"', '"reported"'))
    archive = export_review(workspace, key, sha)
    inputs = validate_restore_backup(archive)
    assert inputs["source.kicad_pcb"] == original.read_bytes()
    assert inputs["source.kicad_sch"] == (staged / "source.kicad_sch").read_bytes()
    assert set(inputs) == {"source.kicad_pcb", "source.kicad_sch"}
    assert b"forged fab approved" not in b"".join(inputs.values())


def test_restore_blocks_fake_zip_traversal_symlink_oversize_and_sha_mismatch(tmp_path: Path) -> None:
    import stat

    from review_studio_library import validate_restore_backup

    workspace, key, sha, original, review, staged = local_import(tmp_path)
    (staged / "source.kicad_sch").write_bytes(b"(kicad_sch " + b"x" * 200 + b")")
    archive = export_review(workspace, key, sha)
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        original_members = {member.filename: z.read(member) for member in z.infolist()}

    def make(changes: dict[str, bytes], omit: tuple[str, ...] = ()) -> bytes:
        file = io.BytesIO()
        with zipfile.ZipFile(file, "w", zipfile.ZIP_DEFLATED) as z:
            for name, value in (original_members | changes).items():
                if name not in omit:
                    z.writestr(name, value)
        return file.getvalue()

    for unsafe in (
        "selected-input-copies/../file.kicad_sch",
        "selected-input-copies/../../etc/passwd",
        "selected-input-copies/sub\\evil.kicad_sch",
        "/selected-input-copies/source.kicad_pcb",
    ):
        with pytest.raises(ValueError):
            validate_restore_backup(make({unsafe: b"(kicad_sch " + b"x" * 200}))
    with pytest.raises(ValueError, match="SHA256"):
        validate_restore_backup(make({"selected-input-copies/source.kicad_pcb": b"(kicad_pcb modified" + b"x" * 240}))
    with pytest.raises(ValueError, match="format header"):
        validate_restore_backup(make({}, ("README-LOCAL-BACKUP.txt",)))
    with pytest.raises(ValueError, match="decompressed size"):
        validate_restore_backup(make({"review/very-big.svg": b"X" * (80 * 1024 * 1024 + 1)}))
    symlink_zip = io.BytesIO()
    with zipfile.ZipFile(symlink_zip, "w") as z:
        for member, raw in original_members.items():
            z.writestr(member, raw)
        link = zipfile.ZipInfo("selected-input-copies/sub/evil.kicad_sch")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(link, "../../.ssh/id_rsa")
    with pytest.raises(ValueError, match="Symbolic"):
        validate_restore_backup(symlink_zip.getvalue())


def test_generated_kicad_session_is_excluded_from_new_backups_but_old_archives_restore(tmp_path: Path) -> None:
    from review_studio_library import validate_restore_backup

    workspace, key, sha, original, review, stage = local_import(tmp_path)
    (stage / "source.kicad_sch").write_bytes(b"(kicad_sch" + b"x" * 300 + b")")
    (stage / "source.kicad_prl").write_text('{"recent project paths": "/home/user/private/customer"}')
    current = export_review(workspace, key, sha)
    with zipfile.ZipFile(io.BytesIO(current)) as z:
        assert not any(".kicad_prl" in name for name in z.namelist())
        originals = [(info.filename, z.read(info)) for info in z.infolist()]
    assert all(b"/home/user/private/customer" not in raw for _, raw in originals)
    legacy = io.BytesIO()
    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, content in originals:
            z.writestr(name, content)
        z.writestr("selected-input-copies/source.kicad_prl", "private KiCad generated session state")
    sources = validate_restore_backup(legacy.getvalue())
    assert sources["source.kicad_pcb"] == original.read_bytes()
    assert "source.kicad_prl" not in sources
    assert "source.kicad_sch" in sources

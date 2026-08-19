from __future__ import annotations

from zaptrace.agent import _tool_impls
from zaptrace.core.models import Design, DesignMeta
from zaptrace.core.session_store import SessionDesignStore


def test_session_design_store_writes_current_and_version(tmp_path) -> None:
    store = SessionDesignStore(tmp_path, "session-a")
    design = Design(meta=DesignMeta(name="persisted"))
    manifest = store.write_design("persisted", design)
    assert manifest["schema_version"] == "1.0"
    assert (tmp_path / manifest["current_path"]).exists()
    assert (tmp_path / manifest["version_path"]).exists()
    assert store.load_designs()["persisted"].meta.name == "persisted"


def test_get_session_hydrates_designs_from_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZAPTRACE_SESSION_STORE_ROOT", str(tmp_path))
    _tool_impls._sessions.clear()
    session = _tool_impls._get_session("s1")
    session["designs"]["persisted"] = Design(meta=DesignMeta(name="persisted"))
    _tool_impls._sessions.clear()
    hydrated = _tool_impls._get_session("s1")
    assert "persisted" in hydrated["designs"]
    assert hydrated["designs"]["persisted"].meta.name == "persisted"

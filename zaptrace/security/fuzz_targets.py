"""Adapters for bounded untrusted-input fuzz targets."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


class FuzzRejectError(Exception):
    """The target rejected malformed input through its public error contract."""


class FuzzContainmentError(RuntimeError):
    """The target produced a path outside its configured boundary."""


def _reject_on(expected: tuple[type[Exception], ...], operation: Callable[[], Any]) -> None:
    try:
        operation()
    except expected as exc:
        raise FuzzRejectError(f"{type(exc).__name__}: {exc}") from exc


def _decode(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


def design_yaml(payload: bytes, _workspace: Path) -> None:
    from zaptrace.core.exceptions import ParseError
    from zaptrace.core.parser import parse_str

    _reject_on((ParseError,), lambda: parse_str(_decode(payload), source="fuzz:design_yaml"))


def requirements_schema(payload: bytes, _workspace: Path) -> None:
    import yaml
    from pydantic import ValidationError

    from zaptrace.synthesis.requirements import validate_requirements_schema_v1

    def operation() -> None:
        value = yaml.safe_load(_decode(payload))
        if not isinstance(value, Mapping):
            raise ValueError("requirements payload is not a mapping")
        validate_requirements_schema_v1(value)

    _reject_on((ValueError, TypeError, yaml.YAMLError, ValidationError), operation)


def kicad_schematic(payload: bytes, _workspace: Path) -> None:
    from zaptrace.kicad.schematic_importer import import_kicad_schematic_string

    _reject_on((ValueError, TypeError), lambda: import_kicad_schematic_string(_decode(payload)))


def kicad_pcb(payload: bytes, workspace: Path) -> None:
    from zaptrace.kicad.importer import import_kicad_pcb

    path = workspace / "input.kicad_pcb"
    path.write_bytes(payload)
    _reject_on((OSError, ValueError, TypeError), lambda: import_kicad_pcb(path))


def easyeda_std(payload: bytes, _workspace: Path) -> None:
    from zaptrace.eda.easyeda_std import read_easyeda_std_json

    _reject_on((ValueError, TypeError), lambda: read_easyeda_std_json(payload))


def easyeda_pro_zip(payload: bytes, _workspace: Path) -> None:
    from zaptrace.eda.easyeda_pro import read_easyeda_pro_zip

    _reject_on((ValueError, TypeError), lambda: read_easyeda_pro_zip(payload))


def eagle_xml(payload: bytes, _workspace: Path) -> None:
    from zaptrace.eda.eagle import import_eagle_xml_bytes

    _reject_on((ValueError, TypeError), lambda: import_eagle_xml_bytes(payload))


def altium_ascii(payload: bytes, _workspace: Path) -> None:
    from zaptrace.eda.altium import read_altium_ascii_sch

    _reject_on((ValueError, TypeError), lambda: read_altium_ascii_sch(payload))


def plugin_manifest(payload: bytes, _workspace: Path) -> None:
    from pydantic import ValidationError

    from zaptrace.plugin.manifest import PluginManifest

    def operation() -> None:
        value = json.loads(_decode(payload))
        if not isinstance(value, dict):
            raise ValueError("plugin manifest is not an object")
        PluginManifest.model_validate(value)

    _reject_on((json.JSONDecodeError, ValueError, TypeError, ValidationError), operation)


def workspace_path(payload: bytes, workspace: Path) -> None:
    from zaptrace.agent import _tool_impls

    old_workspace = _tool_impls._WORKSPACE
    old_env = os.environ.get("ZAPTRACE_WORKSPACE")
    old_cwd = Path.cwd()
    _tool_impls._WORKSPACE = None
    os.environ["ZAPTRACE_WORKSPACE"] = str(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace)
    try:
        try:
            resolved = _tool_impls._validate_path(_decode(payload), must_exist=False)
        except ValueError as exc:
            raise FuzzRejectError(f"ValueError: {exc}") from exc
        if not resolved.is_relative_to(workspace.resolve()):
            raise FuzzContainmentError(f"accepted path outside workspace: {resolved}")
    finally:
        os.chdir(old_cwd)
        _tool_impls._WORKSPACE = old_workspace
        if old_env is None:
            os.environ.pop("ZAPTRACE_WORKSPACE", None)
        else:
            os.environ["ZAPTRACE_WORKSPACE"] = old_env


def _assert_paths_contained(paths: Sequence[str | Path], root: Path) -> None:
    canonical_root = root.resolve()
    for value in paths:
        path = Path(value).resolve()
        if not path.is_relative_to(canonical_root):
            raise FuzzContainmentError(f"export escaped output root: {path}")


def gerber_prefix(payload: bytes, workspace: Path) -> None:
    from zaptrace.core.models import Design, DesignMeta
    from zaptrace.export.gerber import generate_gerber

    output = workspace / "gerber"
    result = generate_gerber(Design(meta=DesignMeta(name="fuzz")), output, prefix=_decode(payload))
    _assert_paths_contained(tuple(result.values()), output)


def excellon_prefix(payload: bytes, workspace: Path) -> None:
    from zaptrace.core.models import Design, DesignMeta
    from zaptrace.export.excellon import generate_composite_drill

    output = workspace / "drill"
    result = generate_composite_drill(Design(meta=DesignMeta(name="fuzz")), output, prefix=_decode(payload))
    _assert_paths_contained((result,), output)


TARGETS: dict[str, Callable[[bytes, Path], None]] = {
    "design_yaml": design_yaml,
    "requirements_schema": requirements_schema,
    "kicad_schematic": kicad_schematic,
    "kicad_pcb": kicad_pcb,
    "easyeda_std": easyeda_std,
    "easyeda_pro_zip": easyeda_pro_zip,
    "eagle_xml": eagle_xml,
    "altium_ascii": altium_ascii,
    "plugin_manifest": plugin_manifest,
    "workspace_path": workspace_path,
    "gerber_prefix": gerber_prefix,
    "excellon_prefix": excellon_prefix,
}


def api_transaction_request(payload: bytes, _workspace: Path) -> None:
    """Exercise REST request-body validation without starting a server."""
    from pydantic import ValidationError

    from zaptrace.api.models import TransactionPreviewRequest

    def operation() -> None:
        value = json.loads(_decode(payload))
        TransactionPreviewRequest.model_validate(value)

    _reject_on((json.JSONDecodeError, ValueError, TypeError, ValidationError), operation)


def mcp_tool_parameters(payload: bytes, _workspace: Path) -> None:
    """Exercise MCP registry parameter and path validation."""
    from zaptrace.agent._tool_impls import TOOL_REGISTRY
    from zaptrace.mcp.server import _validate_tool_params

    def operation() -> None:
        value = json.loads(_decode(payload))
        if not isinstance(value, dict):
            raise ValueError("MCP parameters are not an object")
        _validate_tool_params(TOOL_REGISTRY["design_parse_file"], value)

    _reject_on((json.JSONDecodeError, ValueError, TypeError), operation)


TARGETS.update(
    {
        "api_transaction_request": api_transaction_request,
        "mcp_tool_parameters": mcp_tool_parameters,
    }
)

# Plugin Development Guide

> Extend ZapTrace with custom tools, exporters, and analyzers.

---

## Current manifest-first contract

Plugins must include a `zaptrace-plugin.json` manifest before ZapTrace will admit them. The manifest declares API compatibility, extension points, capabilities, permissions, and signing metadata. Admission validates the manifest only; it does not import or execute plugin code.

Minimal manifest fixture:

```json
{
  "$schema": "https://zaptrace.dev/schemas/plugin-manifest-v1.json",
  "api_version": "1.0",
  "plugin_id": "dev.example.my-plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "min_zaptrace_version": "0.2.0",
  "max_zaptrace_version": "0.3.5",
  "entry": {"type": "python_module", "path": "my_plugin"},
  "extension_points": ["report_generator"],
  "capabilities": ["design:read", "proof:read", "host:log"],
  "permissions": {
    "filesystem": {"read": [], "write": []},
    "network": {"allowed_domains": [], "allowed_schemes": []},
    "subprocess": false
  },
  "signing": {
    "algorithm": "ed25519",
    "signature": "base64-signature",
    "public_key_fingerprint": "sha256:publisher-key"
  }
}
```

Unsigned plugins are rejected by default. Capabilities such as `subprocess:run`, `plugin:load`, and `mcp:tool_call` require explicit dangerous-capability admission.

## 1. Plugin Architecture

```
zaptrace/plugin/            # Plugin discovery directory
├── my_plugin/               # Plugin package
│   ├── __init__.py          # Plugin class definition
│   ├── tools.py             # MCP tool definitions
│   └── assets/              # Static assets (footprints, etc.)
└── ...
```

Or install via pip:

```bash
pip install zaptrace-my-plugin  # Auto-discovered
```

## 2. Minimal Plugin

```python
# my_plugin/__init__.py
from zaptrace.plugin import BasePlugin, PluginManifest

class MyPlugin(BasePlugin):
    """Custom analysis plugin."""

    manifest = PluginManifest(
        name="my-plugin",
        version="0.1.0",
        description="Custom thermal analysis",
        author="Your Name",
    )

    def register(self) -> None:
        """Register tools with the MCP server."""
        # See tools.py for tool definitions
        pass
```

## 3. Registering MCP Tools

```python
# my_plugin/tools.py
from zaptrace.mcp import tool
from zaptrace.models import Design

@tool(
    name="my_custom_analysis",
    description="Run custom thermal analysis on a design",
    category="analysis",
)
async def custom_thermal_analysis(
    design: Design,
    ambient_temp: float = 25.0,
) -> dict:
    """Analyze thermal characteristics.

    Args:
        design: PCB design to analyze
        ambient_temp: Ambient temperature in Celsius

    Returns:
        Thermal analysis results
    """
    results = []
    for comp in design.components:
        if comp.thermal_resistance:
            temp_rise = comp.power * comp.thermal_resistance
            results.append({
                "ref": comp.ref,
                "temp_rise": temp_rise,
                "junction_temp": ambient_temp + temp_rise,
            })

    return {"components": results, "ambient_temp": ambient_temp}
```

## 4. Custom Exporters

```python
# my_plugin/exporter.py
from zaptrace.export import BaseExporter

class STEPExporter(BaseExporter):
    """Export 3D model as STEP file."""

    format = "step"

    def export(self, design, output_path: str):
        """Generate STEP file from design."""
        # Implementation here
        pass
```

## 5. Distribution

### Package Structure

```
zaptrace-my-plugin/
├── pyproject.toml
├── zaptrace_my_plugin/
│   ├── __init__.py
│   └── tools.py
└── README.md
```

### `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "zaptrace-my-plugin"
version = "0.1.0"
description = "My custom ZapTrace plugin"

[project.entry-points."zaptrace.plugins"]
my_plugin = "zaptrace_my_plugin"

[project.optional-dependencies]
zaptrace = ["zaptrace>=0.2"]
```

## 6. Plugin Discovery

ZapTrace discovers plugins via:

1. **Entry points** — Packages registered under `zaptrace.plugins` in `pyproject.toml`
2. **Built-in package** — `zaptrace/plugin/` contains the current manifest and admission implementation; third-party local-directory discovery remains experimental
3. **User config** — `~/.config/zaptrace/plugins.yaml`
4. **Environment variable** — `ZAPTRACE_PLUGINS=/path/to/plugin`

## 7. Best Practices

- **Isolate state** — Don't mutate global design state without transactions
- **Type hints** — Use Pydantic models for tool parameters
- **Async support** — Use `async def` for I/O bound operations
- **Error handling** — Always return structured errors
- **Testing** — Include `pytest` tests with your plugin
- **Documentation** — README with install, usage, example

# Tutorial: Getting Started

This tutorial gets a new user from a fresh clone to a basic ZapTrace command run.

## Prerequisites

- Python 3.12 or newer.
- `uv` installed.
- Git.
- Optional: KiCad CLI for external ERC/DRC oracle checks.

## Clone and install

```bash
git clone https://github.com/oaslananka/zaptrace.git
cd zaptrace
uv sync --all-extras
```

## Run diagnostics

```bash
uv run zaptrace doctor
```

## Parse an example design

```bash
uv run zaptrace parse examples/esp32_i2c_sensor_node/design.yaml
```

## Run checks

```bash
uv run pytest -q
uv run ruff check .
uv run pyright
```

## Safety reminder

ZapTrace is pre-1.0. Generated schematics, PCB files, manufacturing bundles, and proof packs are review evidence, not fabrication approval. A qualified human engineer must review outputs before fabrication or use.

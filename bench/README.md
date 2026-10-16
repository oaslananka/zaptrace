# Performance benchmarks

These benchmarks measure the deterministic design flow (parse, synthesis,
net classification, placement, routing, ERC, DRC, BOM and KiCad export) with
[pytest-codspeed](https://codspeed.io/docs/reference/pytest-codspeed). They run
in CI through `.github/workflows/codspeed.yml` and are tracked on
[CodSpeed](https://app.codspeed.io/oaslananka/zaptrace).

They live outside `tests/` on purpose: they are not part of the classified test
lanes and do not affect lane budgets or coverage.

Each benchmark runs on two inputs:

- `example`: the committed `examples/esp32_i2c_sensor_node/design.yaml` board;
- `scaled`: a synthetic 12-channel RC/LED design generated in `conftest.py`.

Run locally:

```bash
uv sync --all-extras --all-groups
PYTHONPATH=. uv run pytest bench --codspeed
```

Run with the CodSpeed CPU simulation instrument (requires the `codspeed` CLI):

```bash
PYTHONPATH=. codspeed run --mode simulation -- uv run pytest bench --codspeed
```

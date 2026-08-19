# Static Review Viewer

The static review viewer generates a local browser bundle for design and proof-pack inspection. It does not upload private designs to a cloud service and does not mutate design state.

Generate a viewer bundle:

```bash
zaptrace viewer examples/esp32_i2c_sensor_node/design.yaml --proof examples/esp32_i2c_sensor_node/.proof/proof.yaml --output build/review-viewer
```

Open `build/review-viewer/index.html` in a browser.

The bundle contains:

- `assets/schematic.svg` for the schematic overview;
- `assets/pcb-top.svg` and `assets/pcb-bottom.svg` for local PCB layer review;
- DRC/DFM marker summaries when the design contains validation results;
- `data/bom.json` for BOM summary review;
- `data/proof-summary.json` and `data/viewer-manifest.json` for proof-pack status and artifact provenance.

This is a static inspection artifact for CI and local review. Fabrication still requires explicit ERC/DRC/DFM/proof-pack signoff.

## KiCad review-export bundle

Hardware release CI may attach a separate static `kicad-review-exports/` bundle produced by the KiCad 10 oracle. Its root index links each representative project to the retained ODB++ package and GLB mechanical-review file and shows the mechanical coverage state/limitations from `review-index.json`.

This bundle complements the browser viewer; it does not change viewer approval semantics. In particular, a downloadable GLB with missing or unresolved component models remains `degraded`, and neither the GLB nor ODB++ link is a fabrication, assembly, enclosure-fit, or manufacturer-approval claim. The per-family page also states that KiCad export bytes are not guaranteed identical across reruns: artifact SHA-256 values are run-bound integrity evidence while structural digests are the bounded rerun-comparison surface.

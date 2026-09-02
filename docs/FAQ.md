# ZapTrace FAQ

## General

### What is ZapTrace?
ZapTrace is an AI-native, verification-first, open-source EDA (Electronic Design Automation) kernel. It takes design intent (as YAML or natural language) and produces validated design outputs including Gerber files, BOM, and pick-and-place data. **All outputs require human engineering review before fabrication.**

### Is ZapTrace a KiCad replacement?
No. ZapTrace is a backend engine for programmatic electronics design. You can use it alongside KiCad — ZapTrace generates KiCad-compatible files, and you can open them in KiCad for further editing.

### Is ZapTrace ready for production?
ZapTrace is in alpha development (`0.3.5.dev0`); the latest published PyPI baseline is legacy `v0.3.3` without public Git provenance. The historical `v0.3.2` and `v0.3.4` tagged attempts remain failed-release evidence. The first fully traceable release will be `v0.3.5`. It works for simple to moderate designs, but **all outputs require human review before fabrication**. See [SAFETY.md](SAFETY.md).

### Who is ZapTrace for?
- **AI/Agent developers** building electronics design workflows
- **Embedded engineers** who want programmatic PCB generation
- **Hardware startups** iterating on designs quickly
- **EDA researchers** exploring new placement/routing algorithms
- **Educators** teaching electronics design automation

## Technical

### What design format does ZapTrace use?
ZapTrace uses a YAML-based design format. See the [examples](https://github.com/oaslananka/zaptrace/tree/main/examples) for sample files.

### Can ZapTrace read KiCad files?
Not yet. KiCad export is implemented, but import is planned for a future release.

### What file formats does ZapTrace export?
- Gerber RS-274X (copper layers, solder mask, silkscreen, paste)
- Excellon (drill file)
- BOM (CSV and JSON)
- Pick-and-place (CSV)
- KiCad (schematic and PCB)
- SVG (schematic rendering)
- Markdown (design report)
- ZIP (manufacturing bundle)

### Does ZapTrace support multi-layer boards?
Yes, 2-layer and 4-layer boards are supported. Additional layers are planned.

### How good is the router?
ZapTrace offers two routers:
1. **Manhattan MST router**: Fast, simple, works well for moderate-complexity designs
2. **Grid-based A* router**: Slower but higher quality, with component blocking and layer-aware routing

### Does ZapTrace support curved traces?
Yes, through the fillet algorithm for rounding trace corners.

## MCP

### What is the MCP server?
The MCP server exposes ZapTrace's design tools through the Model Context Protocol, allowing AI agents to interact with ZapTrace programmatically.

### How do I use it?
```bash
zaptrace-mcp
```
Then configure your AI client to connect to it. See [MCP quickstart](mcp/quickstart.md).

## Safety

### Can I trust ZapTrace's outputs?
ZapTrace performs validation (ERC + DRC) and documents all checks. However, **always review outputs before fabrication**. The proof-pack system exists to make this review easier, not to replace it.

### What could go wrong?
- Incorrect pin assignments in the design file
- Missing or wrong footprints
- Electrical errors not caught by ERC
- Physical/mechanical constraints not modeled
- Manufacturing capabilities not matched

See [SAFETY.md](SAFETY.md) for the full disclaimers.

## Development

### How do I contribute?
See [CONTRIBUTING.md](https://github.com/oaslananka/zaptrace/blob/main/CONTRIBUTING.md).

### What's the license?
MIT — free for commercial and personal use.

### How can I report a bug?
Open a [GitHub Issue](https://github.com/oaslananka/zaptrace/issues/new?template=bug_report.yml).

### Do you accept feature requests?
Yes! Open a [Feature Request](https://github.com/oaslananka/zaptrace/issues/new?template=feature_request.yml).

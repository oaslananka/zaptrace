# Pinned native Review Studio source fixture

Read-only local ESP32/Issue #91 review inputs retained for repeatable tests. The original ignored `build/source-reference-readonly/` workspace remains untouched; tests use this distinct fixture copy. Do not treat native DRC/ERC output, stored copper, supplier shapes or generated libraries as fabrication approval.

The YAML, PCB and schematic retain their verified local SHA-256 digests. Run `sha256sum -c SHA256SUMS` from this directory before source-sensitive validation. KiCad `.kicad_prl` and lock files are intentionally excluded.

The original local build-script checksum file, `checksums.sha256`, is retained and
covered by the outer `SHA256SUMS` manifest.

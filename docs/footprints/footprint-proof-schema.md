# Footprint proof schema

`footprint_proof.json` records machine-readable evidence for generated, imported, and vendored land patterns. It is a provenance contract; pad/pin validation and release blocking gates build on this schema.

## Required evidence

A footprint proof includes:

```text
schema_version
package_id
footprint_name
source
pad_count
pin_count
pin_map
pads
courtyard_mm
paste_enabled_pad_count
paste_disabled_pad_count
solder_mask_policy
thermal_pads
pin1
notes
```

## Source provenance

`source` identifies where the land pattern came from:

```text
source_type: generated | vendored | imported | unknown
source_name
source_path
source_sha256
generator
generator_version
attribution
```

Generated footprints use `zaptrace.ee.footprints` and the ZapTrace version. Vendored footprints record the source `.kicad_mod` path and SHA-256.

## Pad and pin evidence

Each pad records:

```text
pad_id
layer
shape
position_mm
size_mm
drill_mm
plated
solder_paste
solder_mask
```

`pin_map` maps logical pin ids to footprint pad ids. When no explicit symbol mapping is supplied, the builder uses `pad.id -> pad.id`.

## Courtyard, paste/mask, and pin-1

`courtyard_mm` records the footprint courtyard extent. Paste evidence is summarized by enabled/disabled pad counts. Solder mask is currently recorded as the policy string plus per-pad assumed mask openings.

`pin1` records whether a pad id such as `1`, `A1`, or `P1` exists. Missing pin-1 evidence is not automatically rejected by this schema, but downstream validators should treat it as a blocking issue for risky packages.

## Fixture

A sample generated proof is committed at:

```text
tests/fixtures/footprints/sot23_footprint_proof.json
```

## Validation diagnostics

`validate_footprint_proof()` emits actionable diagnostics and blocks when any error exists.

Blocking diagnostics include:

```text
pad-count-field-mismatch
pad-pin-count-mismatch
pin-map-count-mismatch
pin-map-pad-missing
unmapped-signal-pad
pin-name-mismatch
missing-pin1-evidence
missing-courtyard
```

Thermal pads are excluded from signal pad count. For example, a QFN-16 footprint with 16 signal pads plus one exposed thermal pad has `pad_count=17`, `pin_count=16`, and should not map the thermal pad as a logical signal pin.

Proof-pack `footprint_proof` evidence maps to sign-off as follows:

```text
passed=false -> footprint-proof fails and blocks autonomous-pass
passed=true  -> footprint-proof passes
```

## Risky package policy

Risky package families require stricter footprint proof review:

```text
AQFN
BGA
DFN
LGA
QFN
RJ45
USB-C / USB_C
```

`validate_risky_package_policy()` requires:

```text
human-reviewed footprint proof or approval_id
source SHA-256 or generator version
pin-1 evidence
non-zero courtyard
complete pin_map
```

Unreviewed risky packages emit `unreviewed-risky-package` and should be attached to proof-pack `footprint_proof` with `passed=false`, which blocks autonomous sign-off through `footprint-proof`.

Non-risky packages such as SOT/SOIC/passive chip packages can still be validated by the normal pad/pin/courtyard checks without the stricter review requirement.

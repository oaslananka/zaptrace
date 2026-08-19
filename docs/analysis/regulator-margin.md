# Regulator dropout and thermal margin evidence

ZapTrace emits a machine-readable regulator margin report for supported regulator profiles. The report is conservative: failures block autonomous sign-off, and missing operating metadata requires human review.

## Inputs

The report consumes:

```text
regulator input/output pins
input_voltage_v / vin_v
output_voltage_v / vout_v
rail load current from rail-current-budget evidence
dropout_voltage_v / ldo_dropout_v
theta_ja_c_per_w
ambient_c
junction_max_c
switcher efficiency when applicable
```

## Report

`build_regulator_margin_report(design)` returns:

```text
schema_version
regulator_count
failure_count
missing_metadata_count
blocked
human_review_required
regulators[]
```

Each regulator entry records input/output nets, voltages, output current, dropout margin, power dissipation, junction estimate, thermal margin, missing fields, status, and message.

## Policy

- Negative LDO dropout margin blocks autonomous sign-off.
- Negative thermal margin blocks autonomous sign-off.
- Missing voltage/current/dropout/thermal metadata requires human review.
- Switcher thermal estimates require explicit efficiency metadata.

## Proof-pack sign-off

Proof manifests can attach `regulator_margin` evidence:

```text
blocked=true                    -> regulator-margin blocks autonomous-pass
human_review_required=true      -> regulator-margin requires human review
passed=true with complete data  -> regulator-margin passes
```

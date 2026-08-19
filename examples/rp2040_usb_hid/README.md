# RP2040 USB HID Controller

A USB HID gamepad/keyboard controller using the Raspberry Pi RP2040.

## Specifications

- **MCU:** RP2040 (QFN-56)
- **USB:** Type-C with ESD protection
- **Inputs:** 8× momentary buttons, 2× analog joysticks
- **Dimensions:** 60×40mm, 2-layer
- **Features:** BOOTSEL button, RGB status LED, 16MB Flash

## Design

```bash
# Create from template
zaptrace new rp2040-usb-hid

# Run autopilot
zaptrace autopilot --design design.yaml

# Export
zaptrace export gerber --output gerber/
zaptrace export bom --output bom.csv
```

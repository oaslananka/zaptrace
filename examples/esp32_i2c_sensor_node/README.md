# ESP32 I2C Sensor Node

A compact ESP32-based sensor node with BME280 temperature/humidity/pressure sensor
on I2C bus, powered by USB-C.

## Specifications

- **MCU:** ESP32-WROOM-32
- **Sensor:** BME280 (I2C address 0x76)
- **Power:** USB-C (5V → 3.3V LDO)
- **Dimensions:** 40×30mm, 2-layer
- **Features:** I2C pull-ups, EN pull-up, boot button, status LED

## Design

```bash
# Create from template
zaptrace new esp32-i2c-sensor

# Run autopilot
zaptrace autopilot --design design.yaml

# Export for manufacturing
zaptrace export gerber --output gerber/
zaptrace export bom --output bom.csv
```

## Files

| File | Description |
|------|-------------|
| `design.yaml` | Complete PCB design |
| `schematic.pdf` | Rendered schematic |
| `gerber/` | Manufacturing outputs |
| `bom.csv` | Bill of materials |

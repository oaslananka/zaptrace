# Vendored footprint land patterns

These `.kicad_mod` files are **unmodified** land patterns copied from upstream,
peer-reviewed, datasheet-derived KiCad footprint libraries. They are vendored so
that module / DFN / LGA / aQFN / magjack packages — which have no parametric
IPC-7351 generator in ZapTrace — get real, verified pad geometry instead of
hand-transcribed coordinates (a single wrong coordinate is a fabrication hazard).

## License

All files here are licensed under **Creative Commons Attribution-ShareAlike 4.0 International (CC-BY-SA-4.0)** with the
KiCad library exception: designs and generated manufacturing files that *use*
these land patterns are not considered adapted material, so boards produced with
ZapTrace are unaffected. The footprint files themselves remain under CC-BY-SA 4.0.

- License: https://creativecommons.org/licenses/by-sa/4.0/legalcode
- KiCad library license terms: https://www.kicad.org/libraries/license/

## Provenance

| File | Package | Used for | Source |
|------|---------|----------|--------|
| `Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod` | LGA-8 | BME280 | KiCad official library (`Package_LGA.pretty`) |
| `SOT-23-6.kicad_mod` | SOT-23-6 / SOT23-6L | USBLC6-2SC6 | KiCad official library (`Package_TO_SOT_SMD.pretty`), revision `91ed84ca84ac27649b4c752bd55edb0aecb5e6de` |
| `SOT-23-8.kicad_mod` | SOT-23-8 / TI DCN candidate | INA219AIDCNR | KiCad official library (`Package_TO_SOT_SMD.pretty`), revision `f35846091d26862be42fa412df7fb00c45b8f3d0`, SHA-256 `f4891c800213c5b817c42db6fd6dcd3f7e1614ae8460cec9e00c03859ad4004d` |
| `SOT-23-5.kicad_mod` | SOT25 / SOT-23-5 | AP2112K-3.3TRG1 | KiCad official library (`Package_TO_SOT_SMD.pretty`), revision `e4191d1fd7b9522beb2980b83ae3c0c2fe41a9e1` |
| `MSOP-10_3x3mm_P0.5mm.kicad_mod` | VSSOP-10 / DGS | ADS1115IDGSR | KiCad official library (`Package_SO.pretty`), revision `e4191d1fd7b9522beb2980b83ae3c0c2fe41a9e1` |
| `MSOP-10_3x3mm_P0.5mm.kicad_mod` | VSSOP-10 / DGS | INA226AIDGSR | KiCad official library (`Package_SO.pretty`), revision `e4191d1fd7b9522beb2980b83ae3c0c2fe41a9e1` |
| `MSOP-8_3x3mm_P0.65mm.kicad_mod` | MSOP-8 3x3 mm P0.65 mm | MCP9808-E/MS review candidate | KiCad official library (`Package_SO.pretty`), revision `c75e8f3ddc65439a5140e7c5b8c6e5b40be0f90e`, SHA-256 `c85207be7edf4b5e1a128249fb05f91b67d622f536fc832d7a9f2a7f1e9a1223` |
| `LQFP-48_7x7mm_P0.5mm.kicad_mod` | LQFP-48 7x7 mm P0.5 mm | STM32G0B1CET6 | KiCad official library (`Package_QFP.pretty`), revision `e4191d1fd7b9522beb2980b83ae3c0c2fe41a9e1` |
| `SOIC-8_3.9x4.9mm_P1.27mm.kicad_mod` | narrow SOIC-8 / Microchip SN/SSH candidates | AT24C02D-SSHM-T, ATECC608B-SSHDA-T | KiCad official library (`Package_SO.pretty`), revision `c75e8f3ddc65439a5140e7c5b8c6e5b40be0f90e`, SHA-256 `074ecb2092b24fa4b4b9cdd7c926fc587b0d7d6d21e7341e57935fd42d36894f` |
| `SOIC-8_5.3x5.3mm_P1.27mm.kicad_mod` | SOIC-8 208-mil / 5.3x5.3 mm P1.27 mm | W25Q128JVSIQ | KiCad official library (`Package_SO.pretty`), revision `e4191d1fd7b9522beb2980b83ae3c0c2fe41a9e1` |
| `Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod` | DFN-8 | SHT31-DIS | KiCad official library (`Sensor_Humidity.pretty`) |
| `Nordic_AQFN-73-1EP_7x7mm_P0.5mm.kicad_mod` | aQFN-73 + exposed die pad | nRF52840 QIAA review candidates | KiCad official library (`Package_DFN_QFN.pretty`), revision `a2cd6bea801640f3b5c0067744ac7f84dc324f1e`, SHA-256 `b1d3fb2b429e53beda8001f4604c456f4561cffd88c65af1f795f147828c0105` |
| `RJ45_Hanrun_HR911105A_Horizontal.kicad_mod` | RJ45 magjack | W5500 Ethernet jack | KiCad official library (`Connector_RJ.pretty`) |
| `ESP32-C3-MINI-1.kicad_mod` | 53-pin module | ESP32-C3-MINI-1 review candidates | Espressif official KiCad library (`espressif/kicad-libraries`) release `3.2.1`, commit `1dfc3110895c9cd62daf332f49c49ee0ee200831` |
| `ESP32-WROOM-32.kicad_mod` | module | ESP32-WROOM-32 | KiCad official library (`RF_Module.pretty`), revision `91ed84ca84ac27649b4c752bd55edb0aecb5e6de` |
| `USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod` | USB-C 16P | GCT USB4105 | KiCad official library (`Connector_USB.pretty`), revision `f10d74936d09738be218aba778f3655cc230fbfc` |
| `Potentiometer_Bourns_3296W_Vertical.kicad_mod` | Bourns 3296W-1 THT | 3296W review candidates | KiCad official library (`Potentiometer_THT.pretty`), revision `a2cd6bea801640f3b5c0067744ac7f84dc324f1e` |
| `Potentiometer_Bourns_3296X_Horizontal.kicad_mod` | Bourns 3296X-1 THT | 3296X review candidates | KiCad official library (`Potentiometer_THT.pretty`), revision `a2cd6bea801640f3b5c0067744ac7f84dc324f1e` |

The KiCad official library and the Espressif library publish under the same
CC-BY-SA 4.0 + exception terms. Files are kept verbatim; update them by copying a
newer upstream revision, not by editing in place.

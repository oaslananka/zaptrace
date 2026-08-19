"""Hardware security review.

A lightweight, deterministic threat-surface review of a design: exposed
debug/programming access, presence (or absence) of a secure element, and MCU
secure-boot / readout-protection reminders — so security is considered during
design, not after a product ships with an open JTAG port.

Findings are advisory; this is not a substitute for a real threat model.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from zaptrace.analysis.dft import analyze_testability
from zaptrace.core.models import Design

_SECURE_ELEMENT_TOKENS = ("atecc", "se050", "optiga", "atsha", "secure-element", "secure_element", "a71ch")
_MCU_TOKENS = ("mcu", "esp32", "stm32", "rp2040", "nrf52", "atmega", "samd", "ch32")
_WIRELESS_TOKENS = ("esp32", "nrf52", "wifi", "ble", "lora", "cc2652", "sx1276", "w5500", "w6100")
_CRYPTO_TOKENS = ("aes", "sha", "rsa", "ecc", "ecdsa", "tls", "ssl", "chacha")
_POWER_GLITCH_TOKENS = ("ldo", "buck", "boost", "regulator", "smps", "pmic", "bq", "mcp73")


@dataclass(frozen=True)
class SecurityFinding:
    topic: str
    severity: str  # "info" | "warning"
    detail: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _any_type_contains(design: Design, tokens: tuple[str, ...]) -> bool:
    return any(any(tok in c.type.lower() for tok in tokens) for c in design.components.values())


def security_review(design: Design) -> list[SecurityFinding]:
    """Return advisory hardware-security findings for *design*."""
    findings: list[SecurityFinding] = []

    if analyze_testability(design).has_debug_access:
        findings.append(
            SecurityFinding(
                topic="debug-exposure",
                severity="warning",
                detail="A debug/programming interface (SWD/JTAG/UART) is exposed.",
                recommendation="Enable readout protection (RDP/CRP) and/or ship a DNP debug-header variant.",
            )
        )

    if _any_type_contains(design, _SECURE_ELEMENT_TOKENS):
        findings.append(
            SecurityFinding(
                topic="secure-element",
                severity="info",
                detail="A secure element is present.",
                recommendation="Use it for key storage, secure boot, and device attestation.",
            )
        )
    else:
        findings.append(
            SecurityFinding(
                topic="secure-element",
                severity="info",
                detail="No secure element detected.",
                recommendation="If the design stores keys/secrets, add a secure element or use MCU secure storage.",
            )
        )

    if _any_type_contains(design, _MCU_TOKENS):
        findings.append(
            SecurityFinding(
                topic="secure-boot",
                severity="info",
                detail="An MCU is present.",
                recommendation="Enable secure boot and flash readout protection before release.",
            )
        )

    # Wireless connectivity — expanded attack surface
    has_wireless = _any_type_contains(design, _WIRELESS_TOKENS) or any(
        any(tok in net.name.lower() for tok in _WIRELESS_TOKENS) for net in design.nets.values()
    )
    if has_wireless:
        findings.append(
            SecurityFinding(
                topic="wireless-attack-surface",
                severity="warning",
                detail="Wireless connectivity (Wi-Fi/BLE/LoRa) expands the attack surface.",
                recommendation=(
                    "Use TLS/DTLS for all cloud connections, OTA update authentication "
                    "(signed firmware), and disable unnecessary protocols/services."
                ),
            )
        )

    # Supply voltage glitch protection
    has_power_ic = _any_type_contains(design, _POWER_GLITCH_TOKENS)
    if has_power_ic and _any_type_contains(design, _MCU_TOKENS):
        findings.append(
            SecurityFinding(
                topic="voltage-glitch-risk",
                severity="info",
                detail="Power regulation ICs present alongside MCU — glitch attacks may be feasible.",
                recommendation=(
                    "For security-critical products, add voltage glitch detection (brownout, "
                    "supervisory ICs such as MAX823 or STM32 BOR) and ensure VDD filter caps "
                    "are placed close to the MCU."
                ),
            )
        )

    # JTAG lock-out policy
    has_jtag = any("jtag" in net.name.lower() or "tck" in net.name.lower() for net in design.nets.values())
    if has_jtag:
        findings.append(
            SecurityFinding(
                topic="jtag-lockout",
                severity="warning",
                detail="JTAG pins detected — these give physical access to code and memory.",
                recommendation=(
                    "Disable or fuse JTAG in production firmware; use JTAG only on debug/engineering builds."
                ),
            )
        )

    return findings


# ---------------------------------------------------------------------------
# Structured security policy table
# ---------------------------------------------------------------------------

_HARDWARE_SECURITY_POLICIES: list[dict[str, str]] = [
    {
        "policy": "debug-disable",
        "standard": "ENISA IoT security baseline",
        "action": "Disable all debug interfaces (SWD/JTAG/UART console) in production firmware.",
        "severity": "critical",
    },
    {
        "policy": "readout-protection",
        "standard": "ARM TrustZone / ST RDP / NXP CMPA",
        "action": "Set flash readout protection (RDP Level 2 / SWD lock) before shipping.",
        "severity": "critical",
    },
    {
        "policy": "secure-boot",
        "standard": "PSA Certified / FIDO Device Onboard",
        "action": "Chain-of-trust from ROM → bootloader → application with signature verification.",
        "severity": "high",
    },
    {
        "policy": "key-storage",
        "standard": "NIST SP 800-57",
        "action": "Store private keys in a secure element (ATECC, SE050) or MCU OTP/eFuse, not flash.",
        "severity": "high",
    },
    {
        "policy": "ota-authentication",
        "standard": "SUIT RFC 9019",
        "action": "Authenticate OTA firmware images with ECDSA-P256 or Ed25519 before applying.",
        "severity": "high",
    },
    {
        "policy": "glitch-detection",
        "standard": "Common Criteria EAL4+",
        "action": "Add voltage supervisor (brownout) with configurable trip level close to MCU.",
        "severity": "medium",
    },
    {
        "policy": "physical-tamper",
        "standard": "FIPS 140-2 Level 3",
        "action": "For high-security products: add a tamper-detect line (case-open switch) wired to MCU GPIO.",
        "severity": "medium",
    },
    {
        "policy": "side-channel",
        "standard": "ISO/IEC 17825",
        "action": "Decouple crypto cores from shared VDD; route clock traces in low-emission topology.",
        "severity": "medium",
    },
]


def hardware_security_policies() -> list[dict[str, str]]:
    """Return the hardware security policy table for a design review.

    Each policy entry includes the required action, the reference standard,
    and a severity rating. This is advisory, not a certification.
    """
    return list(_HARDWARE_SECURITY_POLICIES)

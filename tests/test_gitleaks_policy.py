"""Contracts for precise historical Gitleaks false-positive suppression."""

from __future__ import annotations

from pathlib import Path


def test_gitleaks_ignore_contains_only_exact_historical_fingerprints() -> None:
    lines = [
        line.strip()
        for line in Path(".gitleaksignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(lines) == 13
    assert all(line.count(":") == 3 for line in lines)
    assert all("*" not in line for line in lines)
    assert {line.split(":", 1)[0] for line in lines} == {
        "506e35ee5b55f7fcf1f086060877f27d764a5664",
        "dac7350f0bd866491d1bec57c8761320a4dd162e",
    }

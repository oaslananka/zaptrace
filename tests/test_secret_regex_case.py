from __future__ import annotations

from zaptrace.security.sandbox import redact_secrets


def test_case_insensitive_secret_alphabets_remain_supported() -> None:
    samples = (
        "Authorization: Bearer AbCdEf0123456789-._~+/",
        "x-api-" + "key: " + "AbCdEf" + "012345",
        'password = "MixedCaseSecret123"',
    )
    for sample in samples:
        assert "[REDACTED]" in redact_secrets(sample)

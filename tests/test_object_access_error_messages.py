"""Regression coverage for stable object-authorization error messages."""

from zaptrace.security.objects import (
    _DELEGATE_PRINCIPAL_REQUIRED,
    _TARGET_OBJECT_DENIED,
)


def test_object_authorization_error_messages_remain_stable() -> None:
    assert _TARGET_OBJECT_DENIED == "principal is not authorized for the target object"
    assert _DELEGATE_PRINCIPAL_REQUIRED == "delegate principal is required"

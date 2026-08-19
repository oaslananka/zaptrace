class ZapTraceError(Exception):
    """Base exception for all ZapTrace errors."""


class ParseError(ZapTraceError):
    """Raised when design YAML cannot be parsed or validated."""


class ValidationError(ZapTraceError):
    """Raised when design data is structurally invalid."""


class LibraryError(ZapTraceError):
    """Raised when a component cannot be found in the library."""


class ERCError(ZapTraceError):
    """Raised when ERC detects blocking errors and execution is halted."""


class RoutingError(ZapTraceError):
    """Raised when PCB routing fails completely."""


class SynthesisError(ZapTraceError):
    """Raised when design synthesis cannot produce a valid output."""


class ExportError(ZapTraceError):
    """Raised when an export operation fails."""

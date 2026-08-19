# ZapTrace — Agent-native electronics design core
from zaptrace._version import __version__
from zaptrace.core.models import Component, Design, Net, resolve_variant
from zaptrace.core.parser import parse_file, parse_str

__all__ = [
    "__version__",
    "Design",
    "Component",
    "Net",
    "resolve_variant",
    "parse_file",
    "parse_str",
]

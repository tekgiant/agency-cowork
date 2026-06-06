"""Prompt guard stub — injection scanning disabled when full module is not installed."""

class _CleanResult:
    """Minimal result object matching the real PromptGuard API surface."""
    clean = True
    max_severity = None
    findings = []
    injections = []

_CLEAN = _CleanResult()

def scan_for_injections(text, **kwargs):
    """No-op stub: always returns clean (no injections detected)."""
    return _CLEAN

def log_injection_event(*args, **kwargs):
    """No-op stub."""
    pass

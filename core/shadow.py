"""Per-vendor + global shadow-mode gate.

A vendor goes into shadow mode (no real send, no Rithum mark) if EITHER:
  - global config.SHADOW_MODE is true, OR
  - the vendor row's config_json.force_shadow is true

This lets ops flip the global off (REV'IT live) while keeping individual
vendors caged (e.g. Leatt still dry-running until its sign-off lands).
"""
import config


def is_shadow(vendor_config: dict | None) -> bool:
    """True if this vendor should be in shadow mode (skip real outbound calls)."""
    if config.SHADOW_MODE:
        return True
    return bool((vendor_config or {}).get("force_shadow"))


def reason(vendor_config: dict | None) -> str:
    """Human-readable reason for the shadow status (for logs / dashboard)."""
    if config.SHADOW_MODE:
        return "global SHADOW_MODE"
    if (vendor_config or {}).get("force_shadow"):
        return "vendor.force_shadow"
    return ""

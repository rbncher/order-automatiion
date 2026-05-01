"""Per-vendor shadow override gating."""
from unittest.mock import patch

from core import shadow


def test_global_shadow_overrides_everything():
    with patch.object(shadow.config, "SHADOW_MODE", True):
        assert shadow.is_shadow(None) is True
        assert shadow.is_shadow({}) is True
        assert shadow.is_shadow({"force_shadow": False}) is True
        assert "global" in shadow.reason({"force_shadow": False})


def test_per_vendor_shadow_when_global_off():
    with patch.object(shadow.config, "SHADOW_MODE", False):
        assert shadow.is_shadow({"force_shadow": True}) is True
        assert shadow.reason({"force_shadow": True}) == "vendor.force_shadow"


def test_no_shadow_when_neither_set():
    with patch.object(shadow.config, "SHADOW_MODE", False):
        assert shadow.is_shadow({}) is False
        assert shadow.is_shadow(None) is False
        assert shadow.is_shadow({"force_shadow": False}) is False
        assert shadow.reason({}) == ""


def test_force_shadow_truthy_values():
    with patch.object(shadow.config, "SHADOW_MODE", False):
        # Anything truthy in JSON config counts (string "true", 1, etc.)
        assert shadow.is_shadow({"force_shadow": 1}) is True
        assert shadow.is_shadow({"force_shadow": "yes"}) is True
        assert shadow.is_shadow({"force_shadow": 0}) is False
        assert shadow.is_shadow({"force_shadow": ""}) is False

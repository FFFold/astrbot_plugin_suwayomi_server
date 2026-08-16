"""Tests for suwayomi/config.py — grouped config helpers and legacy migration."""
import json
from pathlib import Path

from suwayomi.config import (
    CONFIG_GROUPS,
    MIGRATE_FLAG_KEY,
    _LEGACY_KEY_DEFAULTS,
    flatten_config,
    get_config_value,
    migrate_legacy_config,
    set_config_value,
)


def _schema() -> dict:
    return json.loads(
        (Path(__file__).resolve().parent.parent / "_conf_schema.json").read_text(
            encoding="utf-8"
        )
    )


def test_legacy_defaults_match_schema():
    """_LEGACY_KEY_DEFAULTS must stay in sync with the invisible keys' defaults.

    If they diverge, Core-refilled defaults would be mistaken for real user
    values and clobber grouped config during migration.
    """
    schema = _schema()
    for key, default in _LEGACY_KEY_DEFAULTS.items():
        entry = schema[key]
        assert entry.get("invisible") is True, f"{key} must be invisible"
        assert entry.get("default") == default, f"{key} default mismatch"


def test_group_layout_covers_all_keys():
    """Every key belongs to exactly one group."""
    seen = [k for keys in CONFIG_GROUPS.values() for k in keys]
    assert len(seen) == len(set(seen))


def test_get_config_value_grouped():
    cfg = {"server": {"server_url": "http://x:4567", "auth_mode": "jwt"}}
    assert get_config_value(cfg, "server_url") == "http://x:4567"
    assert get_config_value(cfg, "auth_mode") == "jwt"
    assert get_config_value(cfg, "username", "u") == "u"


def test_get_config_value_legacy_flat_fallback():
    """Old flat config keys still resolve."""
    cfg = {"server_url": "http://legacy:4567", "check_interval": 30}
    assert get_config_value(cfg, "server_url") == "http://legacy:4567"
    assert get_config_value(cfg, "check_interval") == 30
    assert get_config_value(cfg, "max_pages", 30) == 30


def test_set_config_value_writes_group_and_removes_flat():
    cfg = {"server_url": "http://old:4567"}
    set_config_value(cfg, "server_url", "http://new:4567")
    assert cfg["server"]["server_url"] == "http://new:4567"
    assert "server_url" not in cfg
    assert set(cfg) == {"server"}


def test_set_config_value_merges_into_existing_group():
    cfg = {"server": {"server_url": "http://x:4567"}, "username": "u"}
    set_config_value(cfg, "username", "v")
    assert cfg["server"] == {"server_url": "http://x:4567", "username": "v"}
    assert "username" not in cfg


def test_set_config_value_unknown_key_noop():
    cfg = {"evil": 1}
    set_config_value(cfg, "evil", 2)
    assert cfg == {"evil": 1}


def test_flatten_config_grouped_and_flat():
    cfg = {
        "server": {"server_url": "http://x:4567", "password": "pw"},
        "check_interval": 60,
        "unknown": 1,
    }
    flat = flatten_config(cfg, ["server_url", "check_interval", "unknown"])
    assert flat == {"server_url": "http://x:4567", "check_interval": 60, "unknown": 1}


def test_migrate_legacy_config_moves_flat_keys():
    cfg = {
        "server_url": "http://legacy:4567",
        "auth_mode": "basic",
        "max_pages": 10,
        "already_grouped": True,
    }
    assert migrate_legacy_config(cfg) is True
    assert cfg["server"] == {"server_url": "http://legacy:4567", "auth_mode": "basic"}
    assert cfg["reading"] == {"max_pages": 10}
    assert "server_url" not in cfg
    assert "max_pages" not in cfg
    assert cfg["already_grouped"] is True
    assert cfg[MIGRATE_FLAG_KEY] is True  # migration flag set


def test_migrate_legacy_config_overrides_group_defaults():
    """Schema auto-fill may have created group defaults; legacy values win."""
    cfg = {"server_url": "http://custom:4567", "server": {"server_url": "http://default:4567"}}
    assert migrate_legacy_config(cfg) is True
    assert cfg["server"]["server_url"] == "http://custom:4567"
    assert cfg[MIGRATE_FLAG_KEY] is True


def test_migrate_legacy_config_normalizes_string_values():
    """Hand-edited string values are normalized when migrated into groups."""
    cfg = {
        "chapter_cache_hours": "6",  # string equal to default → placeholder kept
        "check_interval": "30",  # string, non-default → migrated as int
        "max_pages": "abc",  # not convertible → skipped, left as-is
        "enable_ai_tools": "false",  # string bool → migrated as False
    }
    assert migrate_legacy_config(cfg) is True
    assert cfg["chapter_cache_hours"] == "6"  # placeholder untouched
    assert cfg["advanced"]["check_interval"] == 30
    assert isinstance(cfg["advanced"]["check_interval"], int)
    assert "check_interval" not in cfg
    assert cfg["max_pages"] == "abc"  # unparseable value never reaches groups
    assert "max_pages" not in cfg.get("reading", {})
    assert cfg["ai"]["enable_ai_tools"] is False
    assert isinstance(cfg["ai"]["enable_ai_tools"], bool)


def test_migrate_legacy_config_keeps_grouped_values_vs_refilled_defaults():
    """Core-refilled legacy defaults must never clobber real grouped config.

    Regression: after the legacy config was once wiped by Core, the user
    re-enters grouped values; on the next load Core refills invisible legacy
    keys with defaults and a naive migration would overwrite those values.
    """
    cfg = {
        "server": {"server_url": "http://grouped:4567", "auth_mode": "jwt"},
        "server_url": "http://localhost:4567",  # Core-refilled default
        "auth_mode": "none",  # Core-refilled default
        "max_pages": 30,  # Core-refilled default
    }
    assert migrate_legacy_config(cfg) is True  # flag set
    assert cfg["server"]["server_url"] == "http://grouped:4567"  # untouched
    assert cfg["server"]["auth_mode"] == "jwt"  # untouched
    # Refilled defaults are kept as inert placeholders (dropping them would
    # make Core re-add them every load, logging "Config key missing").
    assert cfg["server_url"] == "http://localhost:4567"
    assert cfg["auth_mode"] == "none"
    assert cfg["max_pages"] == 30


def test_migrate_legacy_config_defaults_kept_when_no_real_values():
    """Fresh install: all-default legacy keys stay as placeholders, flag set."""
    cfg = {"server_url": "http://localhost:4567", "auth_mode": "none"}
    assert migrate_legacy_config(cfg) is True
    assert cfg == {
        "server_url": "http://localhost:4567",
        "auth_mode": "none",
        MIGRATE_FLAG_KEY: True,
    }


def test_migrate_legacy_config_noop_when_already_grouped():
    cfg = {"server": {"server_url": "http://x:4567"}}
    assert migrate_legacy_config(cfg) is True  # flag set (nothing to migrate)
    assert cfg == {"server": {"server_url": "http://x:4567"}, MIGRATE_FLAG_KEY: True}


def test_migrate_legacy_config_noop_after_flag_set():
    """Once migrated, Core re-added legacy defaults must never override groups."""
    cfg = {
        "server": {"server_url": "http://grouped:4567"},
        "server_url": "http://refilled-default:4567",  # re-added by Core sync
        MIGRATE_FLAG_KEY: True,
    }
    assert migrate_legacy_config(cfg) is False
    assert cfg["server"]["server_url"] == "http://grouped:4567"  # untouched
    assert cfg["server_url"] == "http://refilled-default:4567"  # legacy key kept as-is

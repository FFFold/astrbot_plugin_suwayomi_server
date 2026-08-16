"""Tests for suwayomi/config.py — grouped config helpers and legacy migration."""
from suwayomi.config import (
    CONFIG_GROUPS,
    MIGRATE_FLAG_KEY,
    flatten_config,
    get_config_value,
    migrate_legacy_config,
    set_config_value,
)


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


def test_migrate_legacy_config_noop_when_already_grouped():
    cfg = {"server": {"server_url": "http://x:4567"}}
    assert migrate_legacy_config(cfg) is False
    assert cfg == {"server": {"server_url": "http://x:4567"}}


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

"""Regression tests for config-change state resets (WebUI dashboard save path)."""
import time
from unittest.mock import AsyncMock, MagicMock

from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.cards import CardCache


def _plugin(cards_enabled=True):
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.config = {
        "cards": {
            "result_cards_enabled": cards_enabled,
            "card_render_timeout_sec": 30,
            "t2i_source": "custom",
            "t2i_endpoint": "http://t2i.local:9105",
        },
        "ai": {"enable_ai_tools": False},
    }
    plugin._card_cache = CardCache(ttl=600)
    plugin._card_cooldown_until = 0.0
    plugin._t2i_endpoint_warned = False
    plugin._search_cache = {}
    plugin._ai_send_locks = {}
    plugin._ai_state = MagicMock()
    plugin._bg_task = None
    plugin.html_render = AsyncMock(return_value="/tmp/card.jpg")
    return plugin


def test_config_change_resets_card_cooldown():
    """A fixed T2I endpoint must render immediately, not after the 5-min cooldown."""
    plugin = _plugin()
    plugin._card_cooldown_until = time.time() + 300
    assert plugin._result_cards_enabled() is False

    plugin._reset_after_config_change()

    assert plugin._card_cooldown_until == 0.0
    assert plugin._result_cards_enabled() is True


def test_config_change_clears_card_cache():
    """Cached images from the previous renderer must not survive a config change."""
    plugin = _plugin()
    plugin._card_cache.put({"card_type": "search"}, "/tmp/stale.jpg")
    assert plugin._card_cache.get({"card_type": "search"}) == "/tmp/stale.jpg"

    plugin._reset_after_config_change()

    assert plugin._card_cache.get({"card_type": "search"}) is None


def test_config_change_resets_t2i_warning_flag():
    plugin = _plugin()
    plugin._t2i_endpoint_warned = True

    plugin._reset_after_config_change()

    assert plugin._t2i_endpoint_warned is False

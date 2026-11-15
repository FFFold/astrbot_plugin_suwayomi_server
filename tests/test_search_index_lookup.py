"""Unit tests for the plugin's search-result index lookup (no network)."""
import time

from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.models import Manga


def _plugin():
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin._search_cache = {}
    return plugin


def _manga(mid=302):
    return Manga(id=mid, source_id=2, url="", title="安达与岛村官方同人集")


def test_lookup_returns_manga_and_count():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time(), {"1": _manga(1), "3": _manga(302)})
    manga, count = plugin._search_index_lookup("u1", "3")
    assert manga.id == 302 and count == 2


def test_lookup_expired_returns_empty():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time() - 601, {"3": _manga()})
    assert plugin._search_index_lookup("u1", "3") == (None, 0)


def test_lookup_is_scoped_to_session():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time(), {"3": _manga()})
    assert plugin._search_index_lookup("u2", "3") == (None, 0)


def test_get_cached_manga_uses_same_cache():
    plugin = _plugin()
    plugin._search_cache["u1"] = (time.time(), {"3": _manga(302)})
    assert plugin._get_cached_manga("u1", "3").id == 302
    assert plugin._get_cached_manga("u1", "9") is None

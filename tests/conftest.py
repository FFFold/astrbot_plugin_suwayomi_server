"""Mock astrbot module for standalone integration tests."""
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Mock astrbot.api before any plugin imports
astrbot_mock = MagicMock()
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_mock.api
sys.modules["astrbot.api.logger"] = astrbot_mock.api.logger
sys.modules["astrbot.api.message_components"] = astrbot_mock.api.message_components


class _FakeFilter:
    """Minimal pass-through decorators so main.py can be imported in tests."""

    def command_group(self, name):
        def deco(fn):
            return _CommandGroup(name)
        return deco

    def group(self, name):
        def deco(fn):
            return _CommandGroup(name)
        return deco

    def command(self, name, **kwargs):
        def deco(fn):
            return fn
        return deco

    def on_astrbot_loaded(self, **kwargs):
        def deco(fn):
            return fn
        return deco

    def after_message_sent(self, **kwargs):
        def deco(fn):
            return fn
        return deco


class _CommandGroup:
    def __init__(self, name):
        self.name = name

    def command(self, name, **kwargs):
        def deco(fn):
            return fn
        return deco

    def group(self, name):
        def deco(fn):
            return _CommandGroup(name)
        return deco


_event_module = MagicMock()
_event_module.filter = _FakeFilter()
_event_module.AstrMessageEvent = type("AstrMessageEvent", (), {})
_event_module.MessageChain = MagicMock()
sys.modules["astrbot.api.event"] = _event_module

_star_module = MagicMock()

class _MockStar:
    pass

class _MockContext:
    pass

_star_module.Star = _MockStar
_star_module.Context = _MockContext
sys.modules["astrbot.api.star"] = _star_module

# Mock AstrBot core modules imported by ai_tools.py so main.py can be imported
# in unit tests without a full AstrBot runtime.
sys.modules.setdefault("astrbot.core", MagicMock())
sys.modules.setdefault("astrbot.core.agent", MagicMock())
_tool_module_mock = MagicMock()

class _MockFunctionTool:
    """Minimal stand-in for astrbot.core.agent.tool.FunctionTool."""

_tool_module_mock.FunctionTool = _MockFunctionTool
sys.modules.setdefault("astrbot.core.agent.tool", _tool_module_mock)

# Allow importing plugin subpackages as a package: utils/* modules use upward
# relative imports (from ..suwayomi import ...), so they must be imported
# through the package root. The on-disk directory name differs between local
# dev (astrbot_suwayomi_server) and GitHub CI checkout (astrbot_plugin_suwayomi_server),
# so register the package under the stable alias `plugin_pkg`.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT.parent))
sys.modules.setdefault("plugin_pkg", importlib.import_module(_PLUGIN_ROOT.name))

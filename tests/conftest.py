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
sys.modules["astrbot.api.event"] = astrbot_mock.api.event
sys.modules["astrbot.api.star"] = astrbot_mock.api.star

# Allow importing plugin subpackages as a package: utils/* modules use upward
# relative imports (from ..suwayomi import ...), so they must be imported
# through the package root. The on-disk directory name differs between local
# dev (astrbot_suwayomi_server) and GitHub CI checkout (astrbot_plugin_suwayomi_server),
# so register the package under the stable alias `plugin_pkg`.
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT.parent))
sys.modules.setdefault("plugin_pkg", importlib.import_module(_PLUGIN_ROOT.name))

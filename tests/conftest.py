"""Mock astrbot module for standalone integration tests."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Allow importing plugin subpackages as a package (e.g. astrbot_suwayomi_server.utils.downloader),
# required because utils/* modules use upward relative imports (from ..suwayomi import ...).
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT.parent))

# Mock astrbot.api before any plugin imports
astrbot_mock = MagicMock()
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_mock.api
sys.modules["astrbot.api.logger"] = astrbot_mock.api.logger
sys.modules["astrbot.api.message_components"] = astrbot_mock.api.message_components
sys.modules["astrbot.api.event"] = astrbot_mock.api.event
sys.modules["astrbot.api.star"] = astrbot_mock.api.star

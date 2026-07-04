"""Mock astrbot module for standalone integration tests."""
import sys
from unittest.mock import MagicMock

# Mock astrbot.api before any plugin imports
astrbot_mock = MagicMock()
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_mock.api
sys.modules["astrbot.api.logger"] = astrbot_mock.api.logger
sys.modules["astrbot.api.message_components"] = astrbot_mock.api.message_components
sys.modules["astrbot.api.event"] = astrbot_mock.api.event
sys.modules["astrbot.api.star"] = astrbot_mock.api.star

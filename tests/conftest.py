import sys
from unittest.mock import MagicMock

# Provide a fake openai module so ai_scoring_service can be imported without the real package
_openai_mock = MagicMock()
sys.modules["openai"] = _openai_mock

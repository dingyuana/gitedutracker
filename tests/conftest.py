import sys
from unittest.mock import MagicMock, patch

import pytest

# Provide a fake openai module so ai_scoring_service can be imported without the real package
_openai_mock = MagicMock()
sys.modules["openai"] = _openai_mock


@pytest.fixture(autouse=True)
def _no_network_mirror(request):
    """全局隔离镜像/git 网络调用；mirror_service 自身测试除外。"""
    if "test_mirror_service" in request.module.__name__:
        yield
        return
    with patch("app.services.pipeline.extract_day_activity",
               return_value={"commits_count": 0, "loc_additions": 0,
                             "loc_deletions": 0, "code_diffs": []}), \
         patch("app.services.pipeline.extract_snapshot",
               return_value={"files": []}), \
         patch("app.services.mirror_service.ensure_mirror",
               side_effect=RuntimeError("network disabled in tests")):
        yield

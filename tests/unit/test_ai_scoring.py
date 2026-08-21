import sys
import os
import pytest
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from app.services.ai_scoring_service import score_student, LLMInvalidResponse


@pytest.fixture
def settings():
    from app.config import Settings
    s = Settings()
    s.llm_base_url = "https://api.openai.com/v1"
    s.llm_api_key = "sk-test"
    s.llm_model = "gpt-4o-mini"
    s.llm_context_max_chars = 500
    return s


@pytest.fixture
def valid_context():
    return {
        "plan_content": "完成用户认证模块的登录和注册功能",
        "commits": [
            {"sha": "abc123", "message": "feat: add login", "additions": 50, "deletions": 10},
            {"sha": "def456", "message": "fix: auth bug", "additions": 5, "deletions": 8},
        ],
        "prs_opened": 1,
        "prs_merged": 0,
        "loc_additions": 55,
        "loc_deletions": 18,
    }


@pytest.fixture
def mock_openai_response():
    return {
        "quality_score": 85,
        "match_score": 90,
        "completion": True,
        "schedule_status": "ontime",
        "comment": "第一段评语\n\n第二段评语\n\n第三段评语\n\n第四段评语",
        "reasoning": "学生完成了登录和注册功能，代码质量良好",
    }


class TestScoreStudentSuccess:

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_returns_parsed_json(self, mock_openai_cls, settings, valid_context, mock_openai_response):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)

        assert result["quality_score"] == 85
        assert result["match_score"] == 90
        assert result["completion"] is True
        assert result["schedule_status"] == "ontime"
        assert result["comment"] == "第一段评语\n\n第二段评语\n\n第三段评语\n\n第四段评语"
        assert result["reasoning"] == "学生完成了登录和注册功能，代码质量良好"

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_calls_openai_with_correct_params(self, mock_openai_cls, settings, valid_context, mock_openai_response):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)
        mock_client.chat.completions.create.return_value = mock_response

        score_student(valid_context, settings)

        mock_client.chat.completions.create.assert_called_once()
        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["model"] == "gpt-4o-mini"
        assert call_kwargs["response_format"]["type"] == "json_object"
        messages = call_kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_user_message_contains_plan_and_activity(self, mock_openai_cls, settings, valid_context, mock_openai_response):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)
        mock_client.chat.completions.create.return_value = mock_response

        score_student(valid_context, settings)

        messages = mock_client.chat.completions.create.call_args[1]["messages"]
        user_message = messages[1]["content"]
        assert "完成用户认证模块的登录和注册功能" in user_message
        assert "feat: add login" in user_message
        assert "fix: auth bug" in user_message
        assert "+55/-18" in user_message

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_quality_score_is_int(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 72,
            "match_score": 80,
            "completion": False,
            "schedule_status": "behind",
            "comment": "需要改进",
            "reasoning": "代码量不足",
        })
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)
        assert isinstance(result["quality_score"], int)
        assert isinstance(result["match_score"], int)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_completion_is_bool(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 60,
            "match_score": 70,
            "completion": True,
            "schedule_status": "ahead",
            "comment": "很好",
            "reasoning": "按时完成",
        })
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)
        assert isinstance(result["completion"], bool)
        assert result["completion"] is True


class TestLLMInvalidResponseMissingField:

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_missing_quality_score_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_missing_match_score_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_missing_completion_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_missing_schedule_status_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_missing_comment_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_missing_reasoning_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_all_missing_fields_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({})
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)


class TestLLMInvalidResponseIllegalJson:

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_non_json_response_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "这不是JSON"
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_invalid_json_syntax_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"quality_score": 80,}'
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)


class TestScheduleStatusEnumValidation:

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_ontime_is_valid(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)
        assert result["schedule_status"] == "ontime"

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_ahead_is_valid(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 90,
            "match_score": 85,
            "completion": True,
            "schedule_status": "ahead",
            "comment": "很好",
            "reasoning": "超额完成",
        })
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)
        assert result["schedule_status"] == "ahead"

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_behind_is_valid(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 60,
            "match_score": 50,
            "completion": False,
            "schedule_status": "behind",
            "comment": "需努力",
            "reasoning": "落后进度",
        })
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)
        assert result["schedule_status"] == "behind"

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_invalid_schedule_status_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "late",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_empty_schedule_status_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)


class TestFieldValueTypeValidation:

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_quality_score_float_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80.5,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_quality_score_out_of_range_low_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": -1,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_quality_score_out_of_range_high_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 101,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_match_score_str_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": "80",
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_completion_int_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": 1,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_comment_int_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": 123,
            "reasoning": "ok",
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_reasoning_list_raises(self, mock_openai_cls, settings, valid_context):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "quality_score": 80,
            "match_score": 80,
            "completion": True,
            "schedule_status": "ontime",
            "comment": "好",
            "reasoning": ["a", "b"],
        })
        mock_client.chat.completions.create.return_value = mock_response

        with pytest.raises(LLMInvalidResponse):
            score_student(valid_context, settings)


class TestDiffTruncation:

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_small_commits_no_truncation(self, mock_openai_cls, settings, valid_context, mock_openai_response):
        settings.llm_context_max_chars = 100000
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(valid_context, settings)
        assert result["quality_score"] == 85

        messages = mock_client.chat.completions.create.call_args[1]["messages"]
        user_message = messages[1]["content"]
        # Original commit details should be present (not truncated)
        assert "abc123" in user_message

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_large_commits_truncated(self, mock_openai_cls, settings, mock_openai_response):
        from datetime import date

        large_context = {
            "plan_content": "完成大型项目",
            "commits": [
                {"sha": f"sha{i:040d}", "message": f"commit message {i}", "additions": 1000, "deletions": 500}
                for i in range(50)
            ],
            "prs_opened": 5,
            "prs_merged": 2,
            "loc_additions": 50000,
            "loc_deletions": 25000,
        }
        settings.llm_context_max_chars = 500

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)
        mock_client.chat.completions.create.return_value = mock_response

        result = score_student(large_context, settings)
        assert result["quality_score"] == 85

        messages = mock_client.chat.completions.create.call_args[1]["messages"]
        user_message = messages[1]["content"]
        # Should not contain sha values (truncated)
        assert "sha0000" not in user_message
        # Should still contain commit messages
        assert "commit message" in user_message

    @patch("app.services.ai_scoring_service.OpenAI")
    def test_truncation_preserves_message_and_stats(self, mock_openai_cls, settings, mock_openai_response):
        large_context = {
            "plan_content": "测试计划",
            "commits": [
                {"sha": f"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "message": f"feat: task {i}", "additions": 200, "deletions": 100}
                for i in range(30)
            ],
            "prs_opened": 0,
            "prs_merged": 0,
            "loc_additions": 6000,
            "loc_deletions": 3000,
        }
        settings.llm_context_max_chars = 200

        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(mock_openai_response)
        mock_client.chat.completions.create.return_value = mock_response

        score_student(large_context, settings)

        messages = mock_client.chat.completions.create.call_args[1]["messages"]
        user_message = messages[1]["content"]
        # Should contain messages and stats but not shas
        assert "feat: task 0" in user_message
        assert "feat: task 1" in user_message
        assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in user_message

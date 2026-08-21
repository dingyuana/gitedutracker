from __future__ import annotations

import json
from typing import Any

from openai import OpenAI

from app.config import Settings


class LLMInvalidResponse(Exception):
    """LLM 返回的 JSON 结构不合法或字段校验失败时抛出"""
    pass


VALID_SCHEDULE_STATUSES = {"ahead", "ontime", "behind"}

REQUIRED_FIELDS = (
    "quality_score",
    "match_score",
    "completion",
    "schedule_status",
    "comment",
    "reasoning",
)

SYSTEM_PROMPT = (
    "你是一个代码评估助手。根据学生当天的 GitHub 活动和布置的任务，"
    "评估质量、匹配度、完成情况，并生成四段式鼓励评语。\n"
    "严格返回 JSON，格式：\n"
    '{"quality_score": 0-100, "match_score": 0-100, "completion": true/false, '
    '"schedule_status": "ahead|ontime|behind", '
    '"comment": "四段中文评语", "reasoning": "评估依据"}'
)


def _truncate_context(commits: list[dict], max_chars: int) -> list[dict]:
    """当 commits 总字符数超过 max_chars 时，只保留 message + stats，丢弃 files/patch"""
    total = sum(
        len(c.get("message", "")) + len(str(c.get("additions", 0))) + len(str(c.get("deletions", 0)))
        for c in commits
    )
    if total <= max_chars:
        return commits
    return [
        {
            "sha": c["sha"],
            "message": c["message"],
            "additions": c["additions"],
            "deletions": c["deletions"],
        }
        for c in commits[:20]
    ]


def _build_user_message(context: dict[str, Any], truncated: bool = False) -> str:
    plan_content = context.get("plan_content", "")
    commits = context.get("commits", [])
    prs_opened = context.get("prs_opened", 0)
    prs_merged = context.get("prs_merged", 0)
    loc_additions = context.get("loc_additions", 0)
    loc_deletions = context.get("loc_deletions", 0)

    lines = [f"当日计划：{plan_content}"]
    lines.append("当日活动：")
    lines.append(f"- commits ({len(commits)}):")
    for c in commits:
        if truncated:
            msg = c.get("message", "")
            add = c.get("additions", 0)
            sub = c.get("deletions", 0)
            lines.append(f"  - {msg} (+{add}/-{sub})")
        else:
            sha = c.get("sha", "")[:8]
            msg = c.get("message", "")
            add = c.get("additions", 0)
            sub = c.get("deletions", 0)
            lines.append(f"  - [{sha}] {msg} (+{add}/-{sub})")
    lines.append(f"- PRs opened: {prs_opened}, merged: {prs_merged}")
    lines.append(f"- 代码增删：+{loc_additions}/-{loc_deletions}")

    return "\n".join(lines)


def _validate_response(data: dict) -> dict:
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise LLMInvalidResponse(f"字段缺失: {field}")

    if not isinstance(data["quality_score"], int):
        raise LLMInvalidResponse(f"quality_score 类型错误: 期望 int，得到 {type(data['quality_score']).__name__}")
    if not (0 <= data["quality_score"] <= 100):
        raise LLMInvalidResponse(f"quality_score 越界: {data['quality_score']}")

    if not isinstance(data["match_score"], int):
        raise LLMInvalidResponse(f"match_score 类型错误: 期望 int，得到 {type(data['match_score']).__name__}")
    if not (0 <= data["match_score"] <= 100):
        raise LLMInvalidResponse(f"match_score 越界: {data['match_score']}")

    if not isinstance(data["completion"], bool):
        raise LLMInvalidResponse(f"completion 类型错误: 期望 bool，得到 {type(data['completion']).__name__}")

    if data["schedule_status"] not in VALID_SCHEDULE_STATUSES:
        raise LLMInvalidResponse(f"schedule_status 枚举无效: {data['schedule_status']}")

    if not isinstance(data["comment"], str):
        raise LLMInvalidResponse(f"comment 类型错误: 期望 str，得到 {type(data['comment']).__name__}")
    if not data["comment"]:
        raise LLMInvalidResponse("comment 不能为空")

    if not isinstance(data["reasoning"], str):
        raise LLMInvalidResponse(f"reasoning 类型错误: 期望 str，得到 {type(data['reasoning']).__name__}")
    if not data["reasoning"]:
        raise LLMInvalidResponse("reasoning 不能为空")

    return data


def score_student(context: dict[str, Any], settings: Settings) -> dict:
    """调用 OpenAI 兼容 API 对学生当日活动进行 AI 评分。

    Args:
        context: 包含 plan_content, commits, prs_opened, prs_merged, loc_additions, loc_deletions
        settings: 应用配置对象

    Returns:
        解析并校验后的评分 JSON dict
    """
    max_chars = getattr(settings, "llm_context_max_chars", 12000)
    commits = context.get("commits", [])
    truncated_commits = _truncate_context(commits, max_chars)
    is_truncated = len(truncated_commits) < len(commits) or (
        len(commits) > 0
        and sum(
            len(c.get("message", "")) + len(str(c.get("additions", 0))) + len(str(c.get("deletions", 0)))
            for c in commits
        ) > max_chars
    )
    user_message = _build_user_message({**context, "commits": truncated_commits}, truncated=is_truncated)

    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    if raw is None:
        raise LLMInvalidResponse("LLM 返回内容为空")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise LLMInvalidResponse(f"JSON 解析失败: {e}")

    if not isinstance(data, dict):
        raise LLMInvalidResponse(f"LLM 返回不是 JSON 对象，得到 {type(data).__name__}")

    return _validate_response(data)

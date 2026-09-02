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

FULL_REQUIRED_FIELDS = REQUIRED_FIELDS + ("beyond_requirements", "bonus")

SYSTEM_PROMPT = (
    "你是一个严格的代码评审导师。根据学生当天布置的任务、GitHub 活动以及提供的真实代码，"
    "评估质量、匹配度、完成情况，并生成四段式鼓励评语。\n"
    "语言要求：评语和 reasoning 一律使用简体中文撰写，严禁使用韩文、日文、英文或其他外语，"
    "仅允许在技术术语（如 STM32、USART、GPIO 等）中使用英文字母。\n"
    "评分依据优先级：\n"
    "1. 若提供「当日代码变更(code_diffs)」，必须逐段阅读真实 diff 评估代码质量："
    "结构设计、命名可读性、边界处理、是否含测试，严禁仅凭提交信息推断。\n"
    "2. 若提供「项目代码快照(project_files)」，从整体架构、模块划分、代码一致性角度审核全项目质量，"
    "并结合当日 commits 判断进度贡献。\n"
    "3. 都未提供时才退化为依据提交信息与行数估算，并在 reasoning 中说明局限。\n"
    "进度(schedule_status/completion)依据当日计划与实际产出对照判断。\n"
    "严格返回 JSON，格式：\n"
    '{"quality_score": 0-100, "match_score": 0-100, "completion": true/false, '
    '"schedule_status": "ahead|ontime|behind", '
    '"comment": "四段中文评语", "reasoning": "评估依据"}'
)

FULL_SYSTEM_PROMPT = (
    "你是一个严格的代码评审导师，正在对学生进行「全项目综合评测」：把项目前期布置的全部任务"
    "（在「阶段综合任务」中给出）综合为一个完整任务，评测学生当前提交的完整代码是否符合整体要求。\n"
    "语言要求：评语和 reasoning 一律使用简体中文撰写，严禁使用韩文、日文、英文或其他外语，"
    "仅允许在技术术语（如 STM32、USART、GPIO 等）中使用英文字母。\n"
    "评测要点：\n"
    "1. 将「阶段综合任务」作为完整需求清单，对照「项目代码快照」逐项评估整体完成度、架构设计、"
    "模块划分、代码一致性、边界处理与可读性，而不是只关注某一天的提交。\n"
    "2. 特别分析学生代码中是否包含超出项目设计要求的部分功能（beyond_requirements），"
    "例如额外模块、自定义特性、工程化改进、单元测试等；有则列出并在 0-15 范围内给出合理加分"
    "（bonus），无则 beyond_requirements 返回空数组、bonus 返回 0。\n"
    "3. 进度(schedule_status/completion)依据整体实现情况对照全部任务判断。\n"
    "4. 鼓励性要求：评语要比逐日评测更充分地肯定学生在整个项目周期中的坚持与成长，语气更积极、更有力。\n"
    "严格返回 JSON，格式：\n"
    '{"quality_score": 0-100, "match_score": 0-100, "completion": true/false, '
    '"schedule_status": "ahead|ontime|behind", '
    '"beyond_requirements": ["超出设计的功能描述", ...], "bonus": 0-15, '
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
    if context.get("eval_mode") == "full":
        return _build_full_user_message(context)
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

    code_diffs = context.get("code_diffs") or []
    if code_diffs:
        lines.append("")
        lines.append("当日代码变更（真实 diff，据此评估质量）：")
        for d in code_diffs[:5]:
            lines.append(f"--- {d.get('message', '')} ---")
            lines.append(str(d.get("patch", ""))[:1200])

    project_files = context.get("project_files") or []
    if project_files:
        lines.append("")
        lines.append("项目当前代码快照（全量审核模式）：")
        for f in project_files:
            lines.append(f"=== {f['path']}{'（截断）' if f.get('truncated') else ''} ===")
            lines.append(str(f.get("content", ""))[:1500])

    return "\n".join(lines)


def _build_full_user_message(context: dict[str, Any]) -> str:
    plan_content = context.get("plan_content", "")
    loc_additions = context.get("loc_additions", 0)

    lines = [f"阶段综合任务：{plan_content}"]
    lines.append(f"- 学生项目累计代码量：约 {loc_additions} 行（全部提交增删之和）")
    lines.append("- 本次为全项目综合评测，无单日 diff，请以整体实现为依据评分")

    project_files = context.get("project_files") or []
    if project_files:
        lines.append("")
        lines.append("项目当前代码快照（据此评估整体质量与超出设计要求的功能）：")
        for f in project_files:
            lines.append(f"=== {f['path']}{'（截断）' if f.get('truncated') else ''} ===")
            lines.append(str(f.get("content", ""))[:1500])

    return "\n".join(lines)


def _is_chinese(text: str) -> bool:
    """判断评语是否以简体中文为主。

    统计汉字（CJK 统一表意文字）、谚文（韩文 Hangul）、假名（日文 Kana）的数量：
    - 含韩文或日文 → 非中文
    - 无汉字且非韩文/日文（如纯英文）→ 视为非中文
    允许英文仅作为内嵌技术术语（如 STM32/USART）出现，不影响中文主体。
    """
    hanzi = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    hangul = sum(1 for ch in text if "\uac00" <= ch <= "\ud7a3")
    kana = sum(1 for ch in text if "\u3040" <= ch <= "\u30ff")
    if hangul > 0 or kana > 0:
        return False
    return hanzi > 0


def _validate_response(data: dict, is_full: bool = False) -> dict:
    required = FULL_REQUIRED_FIELDS if is_full else REQUIRED_FIELDS
    for field in required:
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
    if not _is_chinese(data["comment"]):
        raise LLMInvalidResponse("comment 非中文，请使用简体中文撰写评语")

    if not isinstance(data["reasoning"], str):
        raise LLMInvalidResponse(f"reasoning 类型错误: 期望 str，得到 {type(data['reasoning']).__name__}")
    if not data["reasoning"]:
        raise LLMInvalidResponse("reasoning 不能为空")

    if is_full:
        if not isinstance(data["beyond_requirements"], list):
            raise LLMInvalidResponse(
                f"beyond_requirements 类型错误: 期望 list，得到 {type(data['beyond_requirements']).__name__}"
            )
        if not all(isinstance(x, str) for x in data["beyond_requirements"]):
            raise LLMInvalidResponse("beyond_requirements 元素必须为 str")
        if not isinstance(data["bonus"], int):
            raise LLMInvalidResponse(f"bonus 类型错误: 期望 int，得到 {type(data['bonus']).__name__}")
        if not (0 <= data["bonus"] <= 15):
            raise LLMInvalidResponse(f"bonus 越界(应为 0-15): {data['bonus']}")

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
    is_full = context.get("eval_mode") == "full"
    if not is_full:
        commits = context.get("commits", [])
        truncated_commits = _truncate_context(commits, max_chars)
        is_truncated = len(truncated_commits) < len(commits) or (
            len(commits) > 0
            and sum(
                len(c.get("message", "")) + len(str(c.get("additions", 0))) + len(str(c.get("deletions", 0)))
                for c in commits
            ) > max_chars
        )
        context = {**context, "commits": truncated_commits}
    else:
        is_truncated = False
    user_message = _build_user_message(context, truncated=is_truncated)

    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key,
                    timeout=180.0, max_retries=1)
    response = client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": FULL_SYSTEM_PROMPT if is_full else SYSTEM_PROMPT},
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

    return _validate_response(data, is_full=is_full)

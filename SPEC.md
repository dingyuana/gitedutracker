# 学生 GitHub 日报追踪器 — SPEC（全局契约）

> 本文档定义整个项目的完整契约。每个迭代只实现其中一部分。

---

## 一、项目全局 GWT 场景

### Scenario 1: 导入学生
- Given 用户上传 `students.xlsx`（列：学生姓名、邮箱、GitHub仓库）
- When 调用 `POST /api/import/students`
- Then 返回 200 和已导入的学生数量
- And 每条记录写入 Student 表（含邮箱）

### Scenario 2: 导入项目
- Given 用户上传 `projects.xlsx`（列：项目ID、项目名称、Git仓库URL）
- When 调用 `POST /api/import/projects`
- Then 返回 200 和已导入的项目数量
- And 每条记录写入 Project 表

### Scenario 3: 导入每日计划
- Given 用户上传 `daily_plans.xlsx`（列：日期、项目ID、学生ID、计划内容）
- When 调用 `POST /api/import/daily_plans`
- Then 返回 200 和已导入的计划数量
- And `student_id` 为 null 时该计划适用于所有学生

### Scenario 4: 一键今日评测
- Given 数据库中已有学生、项目、计划数据
- When 教师点击「今日评测」按钮
- Then 依次执行：GitHub 同步 → AI 评分 → 评语生成 → 权重算分 → 自动发邮件
- And 最终导出 xlsx 结果文件

### Scenario 5: AI 四维评分
- Given 某学生某项目的当日活动数据已入库
- When 调用 AI 评分服务
- Then 返回 JSON：`code_volume`、`code_quality`、`task_match`、`schedule_status`
- And 评语为四段式：鼓励开头 + 今日成就 + 今日问题 + 改进建议

### Scenario 6: 权重算分
- Given `ScoringConfig` 中配置了 `w1`、`w2`、`w3` 和 LOC 阈值
- When 调用评分引擎
- Then 按权重公式计算总分
- And 进度超前/落后按配置加减分

### Scenario 7: 自动发邮件
- Given AI 评分已写入 Assessment 表
- When 触发邮件发送
- Then 使用 smtplib 向每位学生发送鼓励邮件
- And 邮件内容为四段式评语 + 分数

### Scenario 8: LLM 失败重试
- Given AI 评分调用失败
- When 重试 3 次后仍失败
- Then 落库 saved_context_json，status=failed，next_retry_at=now+2h
- And 后台重试任务 2 小时后自动再次调用

### Scenario 9: 导出 xlsx
- Given 评测已完成
- When 教师点击下载
- Then 返回当日所有学生的评分和评语 xlsx 文件

---

## 二、各迭代 SPEC

### Iter 0 — 工程基础（无代码）

- `SPEC.md` / `PLAN.md` / `AGENT.md` 三件套
- `.env.example`、`requirements.txt`、`.gitignore` 脚手架

### Iter 1 — 配置 + 数据模型

**config/index.py:**
- 从 `.env` 读取：`DATABASE_URL`、`GITHUB_TOKEN`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`SMTP_*`、`ADMIN_PASSWORD`、`AUTO_RUN_TIME`、`TIMEZONE`
- 默认 TIMEZONE=Asia/Shanghai

**models/ 数据模型（SQLModel）:**
```python
# Student: id, name, email, github_repo, created_at
# Project: id, name, git_url, created_at
# DailyPlan: id, date, project_id, student_id(nullable), content, created_at
# GithubActivity: id, student_id, project_id, date, commits, prs, loc_additions, loc_deletions, diff_text
# Assessment: id, student_id, project_id, date, code_volume, code_quality, task_match, schedule_status, comment, total_score, status, attempts, saved_context_json, next_retry_at
# ScoringConfig: id, w1_volume, w2_quality, w3_match, loc_threshold, schedule_bonus, schedule_penalty
```

### Iter 2 — 数据库初始化 + 导入服务

**services/import_service.py:**
- `import_students(filepath) → int`
- `import_projects(filepath) → int`
- `import_daily_plans(filepath) → int`
- 使用 pandas + openpyxl 读取 xlsx

### Iter 3 — GitHub 同步服务

**services/github_service.py:**
- `sync_daily_activity(date) → int`（返回同步记录数）
- 调用 PyGithub 获取每个仓库当日 commits + PRs + LOC
- 结果写入 GithubActivity 表

### Iter 4 — AI 评分服务（含重试）

**services/ai_scoring_service.py:**
- `score_student_day(student_id, date) → Assessment | None`
- 构造 LLM 请求（OpenAI 兼容），发送上下文（plan + github activity）
- 重试 3 次（指数退避），失败后 persist saved_context_json + next_retry_at
- 后台重试任务：`reap_failed_assessments()`

### Iter 5 — 评分引擎 + 评测流水线

**services/scoring_engine.py:**
- `calculate_total(assessment: Assessment, config: ScoringConfig) → float`
- 纯函数，TDD 测试

**services/pipeline.py:**
- `run_daily_assessment(date) → int`（返回成功评估数）
- 调用 github_service → ai_scoring_service → scoring_engine

### Iter 6 — 邮件服务

**services/email_service.py:**
- `send_daily_email(student_id, date) → bool`
- 构造四段式评语邮件，使用 smtplib 发送
- SMTP 配置来自 config

### Iter 7 — API 路由 + 导入/导出

**api/ 路由:**
- `POST /api/import/students` — 上传学生 xlsx
- `POST /api/import/projects` — 上传项目 xlsx
- `POST /api/import/daily_plans` — 上传计划 xlsx
- `POST /api/assess/today` — 一键评测
- `GET /api/assess/export` — 导出 xlsx
- `GET /api/assess/{date}` — 查看某日评测结果

**utils/export.py:**
- `export_daily_results(date) → bytes`（xlsx 文件内容）

### Iter 8 — Web UI + 启动入口

**app.py (FastAPI):**
- 挂载 API 路由 + Jinja2 模板
- 首页：仪表盘（今日结果概览）
- 导入页面：三张表的上传表单
- 评测页面：一键按钮 + 结果列表
- 可选 ADMIN_PASSWORD 登录保护

---

## 三、验收标准

| # | 验收项 | 所在迭代 |
|---|--------|---------|
| 1 | 配置从 .env 读取，无硬编码 | Iter 1 |
| 2 | Student/Project/DailyPlan 模型正确 | Iter 1 |
| 3 | GithubActivity/Assessment/ScoringConfig 模型正确 | Iter 1 |
| 4 | 导入学生 xlsx 并写入数据库 | Iter 2 |
| 5 | 导入项目 xlsx 并写入数据库 | Iter 2 |
| 6 | 导入每日计划 xlsx，null student_id 支持 | Iter 2 |
| 7 | GitHub 同步获取 commits + PRs + LOC | Iter 3 |
| 8 | AI 评分调用 OpenAI 兼容接口 | Iter 4 |
| 9 | LLM 失败重试 3 次后落库 + 2h 重试 | Iter 4 |
| 10 | 评分引擎按权重算分 | Iter 5 |
| 11 | 评测流水线串联 GitHub→AI→评分 | Iter 5 |
| 12 | 邮件发送到学生邮箱 | Iter 6 |
| 13 | 导入 API 返回成功数量 | Iter 7 |
| 14 | 一键评测 API | Iter 7 |
| 15 | 导出 xlsx 结果 | Iter 7 |
| 16 | Web UI 可用，仪表盘正常渲染 | Iter 8 |
| 17 | 全部测试通过（pytest） | Iter 8 |

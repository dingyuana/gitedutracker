# 学生 GitHub 日报追踪器 — SPEC（全局契约）

> 本文档定义整个项目的完整契约。每个迭代只实现其中一部分。

---

## 一、项目全局 GWT 场景

### Scenario 1: 导入学生
- Given 用户上传 `students.xlsx`（列：学生姓名、邮箱、github仓库）
- When 调用 `POST /api/import/students`（前端页面 `/students` 表单提交）
- Then 返回 200 和已导入的学生数量
- And 每条记录写入 Student 表（含邮箱、github_repo）

### Scenario 2: 导入项目
- Given 用户上传 `projects.xlsx`（列：项目名称、描述、开始日期、结束日期）
- When 调用 `POST /api/import/projects`（前端页面 `/projects` 表单提交）
- Then 返回 200 和已导入的项目数量
- And 每条记录写入 Project 表

### Scenario 3: 导入每日计划
- Given 用户上传 `daily_plans.xlsx`（列：日期、项目名称、工作计划、学生姓名）
- When 调用 `POST /api/import/daily_plans`（前端页面 `/plans` 表单提交）
- Then 返回 200 和已导入的计划数量
- And `student_id` 为 null 时该计划适用于所有学生

### Scenario 4: 一键今日评测
- Given 数据库中已有学生、项目、计划数据
- When 教师在首页点击「今日评测」按钮，或调用 `POST /run-today?date=2025-01-15`
- Then 依次执行：GitHub 同步 → AI 评分 → 评语生成 → 权重算分 → 自动发邮件
- And 返回 `{"success": int, "failed": int, "details": [...]}`

### Scenario 5: AI 四维评分
- Given 某学生某项目的当日活动数据已入库
- When 调用 AI 评分服务
- Then 返回 JSON：`quality_score`、`match_score`、`completion`、`schedule_status`、`comment`、`reasoning`
- And 评语为四段式：鼓励开头 + 今日成就 + 今日问题 + 改进建议

### Scenario 6: 权重算分
- Given `ScoringConfig` 中配置了 `w_volume`、`w_quality`、`w_match` 和 LOC 阈值
- When 调用评分引擎 `compute_final(subscores, config)`
- Then 按权重公式计算总分
- And 进度超前/落后按配置加减分

### Scenario 7: 自动发邮件
- Given AI 评分已写入 Assessment 表，status='done'，email_sent=false
- When 触发 `send_daily_comments(target_date, session)`
- Then 使用 smtplib 向每位学生发送鼓励邮件
- And 邮件内容为四段式评语 + 总分

### Scenario 8: LLM 失败重试
- Given AI 评分调用失败（LLMInvalidResponse 或网络错误）
- When 在 pipeline 中捕获异常
- Then 落库 saved_context_json，status='failed'，next_retry_at=now+2h
- And 后台 `retry_failed_assessments()` 会在下次运行（含下次 run_today）时尝试重试

### Scenario 9: 导出 xlsx
- Given 评测已完成
- When 教师点击「导出」链接
- Then 返回当日所有学生的评分和评语 xlsx 文件

### Scenario 10: Web UI 仪表盘
- Given 应用已启动
- When 访问首页 `GET /`
- Then 显示今日评测按钮、学生列表、项目列表、最近一次评测结果

### Scenario 11: 身份认证
- Given `ADMIN_PASSWORD` 已配置
- When 未登录访问页面
- Then 返回 401
- And `POST /api/login` 使用正确密码后可通过 session cookie 访问

### Scenario 12: 定时调度
- Given `AUTO_RUN_TIME` 已配置（cron 表达式）
- When 应用启动
- Then 启动 APScheduler 后台定时任务，在指定时间调用 `run_today`

### Scenario 13: 新增项目
- Given 教师已登录 Web UI
- When 在项目页 `POST /projects` 提交项目名称（可选描述/起止日期）
- Then 项目写入数据库并重定向回项目列表
- And 列表页显示新增项目
- And 缺少必填「项目名称」时返回 422

### Scenario 14: 新增每日计划
- Given 教师已登录 Web UI，且至少存在一个项目
- When 在计划页 `POST /plans` 提交日期、项目、工作计划（可选指定学生）
- Then 计划写入数据库并重定向回计划列表
- And 列表页显示新增计划
- And 缺少必填「日期/项目/工作计划」时返回 422

### Scenario 15: 编辑项目
- Given 教师已登录 Web UI
- When `GET /projects/{id}/edit` 打开编辑表单页
- And `POST /projects/{id}/edit` 提交修改后的名称/描述/日期
- Then 项目数据更新并重定向回项目列表
- And 列表页显示更新后的信息
- And 项目不存在时返回 404

### Scenario 16: 删除项目
- Given 教师已登录 Web UI
- When `POST /projects/{id}/delete` 确认删除
- Then 项目被删除，且其关联的每日计划与评估一并删除
- And 项目不存在时返回 404

### Scenario 17: 编辑每日计划
- Given 教师已登录 Web UI
- When `GET /plans/{id}/edit` 打开编辑表单页
- And `POST /plans/{id}/edit` 提交修改后的日期/项目/内容/学生
- Then 计划数据更新并重定向回计划列表
- And 计划不存在时返回 404

### Scenario 18: 删除每日计划
- Given 教师已登录 Web UI
- When `POST /plans/{id}/delete` 确认删除
- Then 计划被删除并重定向回计划列表
- And 计划不存在时返回 404

---

## 二、接口契约

### 配置层（`app/config/__init__.py`）

```python
class Settings(BaseSettings):
    github_token: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_context_max_chars: int = 12000
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    admin_password: str = ""
    auto_run_time: str = ""
    database_url: str = "sqlite:///./data/github_tracker.db"
    tz: str = "Asia/Shanghai"

    @property
    def require_auth: bool
    # → bool：admin_password 非空时为 True

def get_settings() -> Settings          # singleton
def get_engine(url: str = None) -> Engine
def init_db(engine_url: str = None) -> None
```

### 数据模型（`app/models/__init__.py`）

| 模型 | 字段 |
|------|------|
| `Student` | id, name, email(unique), github_repo, github_url, student_no, created_at |
| `Project` | id, name, description, start_date, end_date, created_at |
| `DailyPlan` | id, project_id(FK), date, content, student_id(FK|null), created_at |
| `GithubActivity` | id, student_id(FK), date, commits_count, commits_json, prs_opened, prs_merged, loc_additions, loc_deletions, status, fetched_at, saved_context_json |
| `Assessment` | id, student_id(FK), project_id(FK), date, quality_score, match_score, volume_score, schedule_status, schedule_adjustment, total_score, comment, status, attempts, next_retry_at, saved_context_json, email_sent, created_at, evaluated_at |
| `ScoringConfig` | id, w_volume, w_quality, w_match, loc_threshold, schedule_bonus, schedule_penalty, updated_at |

### 导入服务（`app/services/import_service.py`）

```python
def import_students(filepath: str, session: Session = None) -> int
# 返回导入条数，缺少必填列时 raise ValueError

def import_projects(filepath: str, session: Session = None) -> int
# 返回导入条数

def import_daily_plans(filepath: str, session: Session = None) -> int
# 返回导入条数，null student_id 时自动跳过该字段
```

### GitHub 服务（`app/services/github_service.py`）

```python
def fetch_activity(repo: str, date: date, github_token: str = None) -> dict
# 返回 {"commits_count": int, "commits": [...], "prs_opened": int,
#       "prs_merged": int, "loc_additions": int, "loc_deletions": int}

class GitHubError(Exception)
class GitHubNotFoundError(GitHubError)
class GitHubPermissionError(GitHubError)
```

### GitHub 同步（`app/services/github_snapshot.py`）

```python
def sync_day(target_date: date, session: Session = None) -> int
# 为所有 Student 同步活动写入 GithubActivity 表，返回成功条数
```

### AI 评分服务（`app/services/ai_scoring_service.py`）

```python
class LLMInvalidResponse(Exception)

def score_student(context: dict, settings: Settings) -> dict
# context 字段: plan_content, commits, prs_opened, prs_merged, loc_additions, loc_deletions
# 返回: {"quality_score": int, "match_score": int, "completion": bool,
#        "schedule_status": "ahead|ontime|behind", "comment": str, "reasoning": str}
# 失败时 raise LLMInvalidResponse
```

### 评分引擎（`app/services/scoring_engine.py`）

```python
def compute_final(subscores: dict, config: ScoringConfig) -> float
# subscores 字段: volume, quality, match, schedule_status, loc
# 返回 0~100 浮点数，保留两位小数
```

### 评测流水线（`app/services/pipeline.py`）

```python
def run_today(target_date: date, session: Session = None) -> dict
# 返回 {"success": int, "failed": int, "details": [...]}
# 串联：sync_day → 查询 DailyPlan → 对每个学生评分 → 权重算分 → 发邮件
```

### 重试服务（`app/services/retry_service.py`）

```python
def retry_failed_assessments(session: Session = None) -> int
# 查询 status='failed' 且 next_retry_at <= now 的 Assessment，逐一重试
# 返回总尝试条数
```

### 邮件服务（`app/services/email_service.py`）

```python
def send_daily_comments(target_date: date, session: Session = None) -> dict
# 返回 {"sent": int, "skipped": int, "failed": int}
```

### 调度器（`app/scheduler.py`）

```python
def start_scheduler() -> BackgroundScheduler | None
# AUTO_RUN_TIME 为空时返回 None，否则启动 APScheduler
```

### 认证中间件（`app/middleware/auth.py`）

```python
def require_auth(request: Request) -> None
# admin_password 为空时直接返回；否则未登录 session cookie 时 raise HTTPException(401)

def login_endpoint(credentials: HTTPBasicCredentials = Depends(security)) -> JSONResponse
# 密码正确时设置 session cookie，返回 200；密码错误时返回 401
```

### API 路由（`app/api/routes.py`）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/` | 首页仪表盘 |
| GET | `/students` | 学生列表页 |
| POST | `/students` | 上传 xlsx 导入学生 |
| GET | `/projects` | 项目列表页 |
| POST | `/projects` | 新增项目（名称/描述/起止日期） |
| GET | `/projects/{id}/edit` | 项目编辑表单页 |
| POST | `/projects/{id}/edit` | 更新项目 |
| POST | `/projects/{id}/delete` | 删除项目（级联删除关联计划与评估） |
| GET | `/plans` | 计划列表页 |
| POST | `/plans` | 新增每日计划（日期/项目/内容/可选学生） |
| GET | `/plans/{id}/edit` | 计划编辑表单页 |
| POST | `/plans/{id}/edit` | 更新计划 |
| POST | `/plans/{id}/delete` | 删除计划 |
| GET | `/config` | 权重配置页 |
| POST | `/config` | 保存权重配置 |
| GET | `/results?date=YYYY-MM-DD` | 评测结果页 |
| GET | `/export?date=YYYY-MM-DD&fmt=xlsx` | 导出 xlsx 下载 |
| POST | `/run-today?date=YYYY-MM-DD` | 一键评测 |

### 导出工具（`app/utils/export.py`）

```python
def export_daily(target_date: date, session: Session = None) -> bytes
# 返回 xlsx 文件的二进制内容
```

### 配置初始化（`app/services/config_seed.py`）

```python
def seed_config(session: Session = None) -> None
# 若 ScoringConfig 表中无记录，插入默认权重
```

---

## 三、各迭代 SPEC

### Iter 0 — 工程基础（无代码）

- `SPEC.md` / `PLAN.md` / `AGENT.md` 三件套
- `.env.example`、`requirements.txt`、`.gitignore` 脚手架

### Iter 1 — 配置 + 数据模型

**config/__init__.py:**
- pydantic-settings `Settings` 类，从 `.env` 读取所有配置
- `get_settings()` 单例模式
- `init_db(engine_url)` 建表入口

**models/__init__.py:**
- `Student`、`Project`、`DailyPlan`、`GithubActivity`、`Assessment`、`ScoringConfig`
- Student 含 `normalize_github_repo` 字段验证器（将完整 URL 转为 `owner/repo`）
- Assessment 含 `UniqueConstraint('student_id', 'project_id', 'date')`

### Iter 2 — 数据库初始化 + 导入服务

**database.py:**
- SQLite 引擎 + `get_session()` 生成器

**services/import_service.py:**
- `import_students` / `import_projects` / `import_daily_plans`
- 支持中英列名自动映射
- `null student_id` 时适用于所有学生

### Iter 3 — GitHub 同步服务

**services/github_service.py:**
- `fetch_activity(repo, date, github_token)` 封装 PyGithub

**services/github_snapshot.py:**
- `sync_day(target_date, session)` 批量同步并落库

### Iter 4 — AI 评分服务 + 重试机制

**services/ai_scoring_service.py:**
- `score_student(context, settings)` 调用 OpenAI 兼容接口
- 上下文裁剪（超过 `llm_context_max_chars` 截断）
- 返回 `LLMInvalidResponse` 异常

**services/retry_service.py:**
- `retry_failed_assessments(session)` 后台重试 2 小时到期的失败评估

### Iter 5 — 评分引擎 + 评测流水线

**services/scoring_engine.py:**
- `compute_final(subscores, config)` 纯函数，LOC 归一化 + 权重加权 + 进度加减分

**services/pipeline.py:**
- `run_today(target_date, session)` 串联全流程
- LLM 失败时 catch `LLMInvalidResponse`，落库 `saved_context_json` + `next_retry_at`
- 最终调用 `send_daily_comments`

### Iter 6 — 邮件服务

**services/email_service.py:**
- `send_daily_comments(target_date, session)` 按学生分组发邮件
- 内置 3 次 SMTP 重试，成功后标记 `email_sent=True`

### Iter 7 — API 路由 + 导出

**api/routes.py:**
- 所有路由集中于单文件
- `GET /export` 和 `POST /run-today` 两个 API 端点
- 模板渲染：`GET /`, `/students`, `/projects`, `/plans`, `/config`, `/results`

**utils/export.py:**
- `export_daily(date, session)` 返回 xlsx bytes

**middleware/auth.py:**
- `require_auth` 请求级认证
- `login_endpoint` Basic Auth 登录

### Iter 8 — Web UI + 启动入口

**main.py:**
- FastAPI 应用入口，挂载路由 + 静态文件 + Jinja2 模板

**scheduler.py:**
- APScheduler 后台定时任务

**templates/:**
- `base.html` / `index.html` / `students.html` / `projects.html` / `plans.html` / `config.html` / `results.html`

---

## 四、验收表

| # | 验收项 | 所在迭代 | 测试文件 | 用例 |
|---|--------|---------|---------|------|
| 1 | 配置从 .env 读取，无硬编码 | Iter 1 | `tests/unit/test_config.py` | `test_load_from_env` |
| 2 | 配置默认值正确 | Iter 1 | `tests/unit/test_config.py` | `test_defaults` |
| 3 | Settings 单例 | Iter 1 | `tests/unit/test_config.py` | `test_singleton` |
| 4 | require_auth 属性 | Iter 1 | `tests/unit/test_config.py` | `test_require_auth_false/true` |
| 5 | init_db 建表 | Iter 1 | `tests/unit/test_config.py` | `test_init_db_creates_tables` |
| 6 | Student/Project/DailyPlan 模型正确 | Iter 1 | `tests/unit/test_models.py` | 15 个用例 |
| 7 | GithubActivity/Assessment/ScoringConfig 模型正确 | Iter 1 | `tests/unit/test_models.py` | 15 个用例 |
| 8 | 导入学生 xlsx 并写入数据库 | Iter 2 | `tests/unit/test_import.py` | `test_import_students_basic` |
| 9 | 导入学生支持中英文列名 | Iter 2 | `tests/unit/test_import.py` | `test_import_students_english_columns` |
| 10 | 导入学生缺邮箱报错 | Iter 2 | `tests/unit/test_import.py` | `test_import_students_missing_email_raises` |
| 11 | 导入项目 xlsx 并写入数据库 | Iter 2 | `tests/unit/test_import.py` | `test_import_projects_basic` |
| 12 | 导入每日计划 xlsx，null student_id | Iter 2 | `tests/unit/test_import.py` | `test_import_daily_plans_all_students` |
| 13 | 导入计划缺日期报错 | Iter 2 | `tests/unit/test_import.py` | `test_import_daily_plans_missing_date_raises` |
| 14 | 导入计划项目不存在报错 | Iter 2 | `tests/unit/test_import.py` | `test_import_daily_plans_project_not_found_raises` |
| 15 | GitHub 同步获取 commits + PRs + LOC | Iter 3 | `tests/unit/test_github.py` | `test_fetch_activity_success` 等 17 个用例 |
| 16 | GitHub 同步落库 | Iter 3 | `tests/unit/test_github_snapshot.py` | `test_sync_day_success` 等 7 个用例 |
| 17 | AI 评分调用 OpenAI 兼容接口 | Iter 4 | `tests/unit/test_ai_scoring.py` | `test_score_student_success` 等 29 个用例 |
| 18 | LLM 返回非法 JSON 报错 | Iter 4 | `tests/unit/test_ai_scoring.py` | `test_invalid_json_response_raises` 等 |
| 19 | LLM 上下文裁剪 | Iter 4 | `tests/unit/test_ai_scoring.py` | `test_context_truncation` 等 |
| 20 | 评分引擎按权重算分 | Iter 5 | `tests/unit/test_scoring_engine.py` | `test_equal_weights_equal_subscores_returns_same_score` 等 6 个用例 |
| 21 | 评分引擎 LOC 归一化 | Iter 5 | `tests/unit/test_scoring_engine.py` | `test_loc_normalization_below_threshold` 等 |
| 22 | 评测流水线串联 GitHub→AI→评分 | Iter 5 | `tests/unit/test_pipeline.py` | `test_run_today_success` 等 9 个用例 |
| 23 | 流水线 LLM 失败不落库 total_score | Iter 5 | `tests/unit/test_pipeline.py` | `test_run_today_llm_failure` 等 |
| 24 | 重试服务重试失败评估 | Iter 4 | `tests/unit/test_retry.py` | `test_retry_failed_assessments_success` 等 5 个用例 |
| 25 | 邮件发送到学生邮箱 | Iter 6 | `tests/unit/test_email.py` | `test_send_daily_comments_success` 等 7 个用例 |
| 26 | 邮件服务失败不影响评分 | Iter 6 | `tests/integration/test_run_today_email.py` | `test_email_failure_does_not_rollback_assessments` 等 4 个用例 |
| 27 | 导出 xlsx 返回 bytes | Iter 7 | `tests/unit/test_export.py` | `test_export_daily_returns_bytes` 等 6 个用例 |
| 28 | 导入 API 返回成功数量 | Iter 7 | `tests/integration/test_routes.py` | 需前端 POST 测试（当前以页面渲染为主） |
| 29 | 一键评测 API | Iter 7 | `tests/integration/test_routes.py` | `test_returns_summary`, `test_success_count_matches_students` |
| 30 | 导出 API 返回 xlsx | Iter 7 | `tests/integration/test_routes.py` | `test_returns_xlsx_bytes`, `test_content_disposition_attachment` |
| 31 | 导出 API 无效格式返回 400 | Iter 7 | `tests/integration/test_routes.py` | `test_invalid_fmt_returns_400` |
| 32 | Web UI 首页渲染 | Iter 8 | `tests/integration/test_routes.py` | `test_returns_200`, `test_page_contains_run_today_button` |
| 33 | Web UI 显示学生/项目列表 | Iter 8 | `tests/integration/test_routes.py` | `test_page_shows_student_count`, `test_shows_project_list` |
| 34 | Web UI 各页面渲染 | Iter 8 | `tests/integration/test_routes.py` | `test_get_students`, `test_get_projects`, `test_get_plans`, `test_get_config`, `test_get_results` |
| 35 | 认证中间件（未配置不拦截） | Iter 8 | `tests/integration/test_auth_schedule.py` | `test_no_auth_when_password_empty` |
| 36 | 认证中间件（已配置拦截） | Iter 8 | `tests/integration/test_auth_schedule.py` | `test_auth_required_when_password_set` |
| 37 | 登录接口成功 | Iter 8 | `tests/integration/test_auth_schedule.py` | `test_login_endpoint_returns_token` |
| 38 | 登录接口失败 | Iter 8 | `tests/integration/test_auth_schedule.py` | `test_login_endpoint_rejects_wrong_password` |
| 39 | 定时调度器启动 | Iter 8 | `tests/integration/test_auth_schedule.py` | `test_scheduler_starts_when_auto_run_time_set` |
| 40 | 配置种子初始化 | Iter 7 | `tests/unit/test_config_seed.py` | `test_seed_creates_default_config`, `test_seed_idempotent_no_duplicate` |
| 41 | 全部测试通过（pytest） | Iter 8 | 全量 | 165 个测试用例 |
| 42 | 学生导入 API（POST /students） | Iter 8 | `tests/integration/test_routes.py` | `TestPostStudentsImport` |
| 43 | 权重保存 API（POST /config） | Iter 8 | `tests/integration/test_routes.py` | `TestPostConfig::test_updates_scoring_config` |
| 44 | 新增项目 API（POST /projects） | Iter 8 | `tests/integration/test_routes.py` | `TestPostCreateProject` |
| 45 | 新增计划 API（POST /plans） | Iter 8 | `tests/integration/test_routes.py` | `TestPostCreatePlan` |
| 46 | 编辑项目（GET/POST /projects/{id}/edit） | Iter 8 | `tests/integration/test_routes.py` | `TestProjectManagement::test_edit_*` |
| 47 | 删除项目（POST /projects/{id}/delete，级联） | Iter 8 | `tests/integration/test_routes.py` | `TestProjectManagement::test_delete_*` |
| 48 | 编辑计划（GET/POST /plans/{id}/edit） | Iter 8 | `tests/integration/test_routes.py` | `TestPlanManagement::test_edit_*` |
| 49 | 删除计划（POST /plans/{id}/delete） | Iter 8 | `tests/integration/test_routes.py` | `TestPlanManagement::test_delete_*` |
| 50 | 项目/计划页含新增/编辑/删除控件 | Iter 8 | `tests/integration/test_routes.py` | `TestPageHasCreateForms`, `TestProjectManagement::test_list_*`, `TestPlanManagement::test_list_*` |
| 51 | 全部测试通过（pytest，含运行期维护补丁） | Iter 8 | 全量 | 191 个测试用例 |

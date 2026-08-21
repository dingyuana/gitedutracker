# 学生 GitHub 日报追踪器 — AGENT

## 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量 / 函数 | snake_case | `find_by_username`, `sync_activity`, `compute_final` |
| 类 | PascalCase | `AppError`, `ScoringConfig`, `GitHubError` |
| 文件 / 目录 | snake_case（Python） | `import_service.py`, `github_snapshot.py` |

**Python 文件命名统一使用 snake_case：**
- `import_service.py`
- `github_service.py`
- `github_snapshot.py`
- `ai_scoring_service.py`
- `scoring_engine.py`
- `email_service.py`
- `retry_service.py`
- `config_seed.py`

## 分层规范（单向依赖）

```
config/     → 纯配置，从 .env 读取，不依赖项目内其他模块
utils/      → 纯工具函数（导出、格式化），不依赖项目内其他模块
models/     → 数据存取（SQLModel），依赖 config
services/   → 业务逻辑，依赖 models + utils
api/        → HTTP 路由 + 参数校验，依赖 services
middleware/ → 请求级中间件，依赖 config
scheduler/  → 定时任务，依赖 services + config
main.py     → 组装 FastAPI 应用，依赖 api + middleware + scheduler
templates/  → Jinja2 HTML 模板
static/     → 静态资源（CSS/JS/图片）
```

**依赖方向：** `main → api/middleware/scheduler → services → models → config / utils`

**禁止跨层调用：** api 不得直接访问 models（必须经过 services），middleware 不得直接访问 services。

## 禁止事项

| 禁止 | 原因 |
|------|------|
| 吞异常（空 except 或 pass） | 必须 raise 或记录日志（`logger.warning/error`） |
| 密钥硬编码 | 所有密钥必须从 `.env` 读取（通过 `get_settings()`） |
| 密码明文存储 | 必须 bcrypt 哈希（如有密码场景） |
| 硬编码邮箱 / 服务器地址 | 必须从 config 读取 |
| 在测试中调用真实 GitHub / LLM / SMTP | 必须 mock |
| 跨层调用（如 api 直接访问 models） | 必须经过 services |
| 在模板中嵌入业务逻辑 | 模板只做渲染，逻辑在 service/route 层 |

## 响应格式

**成功 (200):**
```json
{ "success": true, "data": { ... } }
```

**一键评测 (200):**
```json
{ "success": 2, "failed": 0, "details": [
  { "student_id": 1, "student_name": "张三", "project_id": 1, "status": "done", "total_score": 85.0 }
]}
```

**异常 (400/401/404/422/500):**
```json
{ "detail": "错误描述" }
```

## 开发迭代规范

1. **TDD 红线原则**：每个 Iter 先写测试（RED），再写代码（GREEN）
2. **文件数量限制**：一个 Iter 只新增 1-3 个文件
3. **门禁要求**：上一个 Iter 全部测试通过（全绿）后才能进入下一个 Iter
4. **测试覆盖**：
   - `tests/unit/` — 单元测试（mock 外部依赖）
   - `tests/integration/` — 集成测试（完整链路）
5. **文档语言**：所有文档（SPEC/PLAN/AGENT/README）必须使用中文
6. **提交规范**：每个 Iter 完成后 commit，commit message 格式：`feat: Iter N - 描述`

## 测试规范

- 框架：`pytest`
- Mock 策略：GitHub API、LLM、SMTP 必须 mock，禁止调用真实服务
- Fixtures：使用 `conftest.py` 提供公共 fixtures（如 SQLite in-memory 数据库）
- 每个 Iter 的测试必须与代码同步推进（RED → GREEN）
- 当前共 **165 个测试用例**：12 个单元测试文件 + 3 个集成测试文件

## 迭代规则摘要

| 规则 | 说明 |
|------|------|
| 先测后码 | RED → GREEN，不得反向 |
| 单 Iter 文件数 | ≤ 3 个新增文件 |
| 门禁 | 上一 Iter 全绿后方可进入下一 Iter |
| 文档 | 全中文 |
| 禁止 | 不吞异常、密钥仅来自 .env、密码用 bcrypt、禁止跨层调用 |

## 关键函数速查

| 函数 | 文件 | 说明 |
|------|------|------|
| `get_settings()` | `app/config/__init__.py` | 获取全局配置单例 |
| `init_db(engine_url)` | `app/config/__init__.py` | 创建数据库表 |
| `get_session()` | `app/database.py` | 数据库 session 生成器 |
| `import_students(filepath, session)` | `app/services/import_service.py` | 导入学生 |
| `import_projects(filepath, session)` | `app/services/import_service.py` | 导入项目 |
| `import_daily_plans(filepath, session)` | `app/services/import_service.py` | 导入每日计划 |
| `fetch_activity(repo, date, token)` | `app/services/github_service.py` | 获取单仓库活动 |
| `sync_day(target_date, session)` | `app/services/github_snapshot.py` | 批量同步所有学生 |
| `score_student(context, settings)` | `app/services/ai_scoring_service.py` | 调用 LLM 评分 |
| `compute_final(subscores, config)` | `app/services/scoring_engine.py` | 权重算分（纯函数） |
| `run_today(target_date, session)` | `app/services/pipeline.py` | 一键评测全流程 |
| `retry_failed_assessments(session)` | `app/services/retry_service.py` | 后台重试失败评估 |
| `send_daily_comments(date, session)` | `app/services/email_service.py` | 发送日报邮件 |
| `seed_config(session)` | `app/services/config_seed.py` | 初始化默认权重 |
| `export_daily(date, session)` | `app/utils/export.py` | 导出 xlsx 文件 |
| `start_scheduler()` | `app/scheduler.py` | 启动定时任务 |
| `require_auth(request)` | `app/middleware/auth.py` | 认证中间件 |
| `login_endpoint(credentials)` | `app/middleware/auth.py` | 登录接口 |

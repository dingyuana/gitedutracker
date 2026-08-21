# 学生 GitHub 日报追踪器 — PLAN

## 迭代规划

### Iter 0 — 工程基础（无代码）

| 顺序 | 任务 | 产出文件 | 状态 |
|------|------|---------|------|
| 0.1 | 创建 SPEC.md / PLAN.md / AGENT.md | `SPEC.md`, `PLAN.md`, `AGENT.md` | ✅ |
| 0.2 | 创建 `.env.example` 环境变量模板 | `.env.example` | ✅ |
| 0.3 | 创建 `requirements.txt` 依赖声明 | `requirements.txt` | ✅ |
| 0.4 | 创建 `.gitignore` | `.gitignore` | ✅ |

### Iter 1 — 配置 + 数据模型（2 个文件，18 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 1.1 | 配置读取 | `app/config/__init__.py` | `tests/unit/test_config.py` | 8 | ✅ |
| 1.2 | 数据模型 | `app/models/__init__.py` | `tests/unit/test_models.py` | 15 | ✅ |
| 1.3 | 数据库初始化 | `app/database.py` | — | — | ✅ |

**实际产出：**
- `app/config/__init__.py` — Settings（pydantic-settings）+ `get_settings()` 单例 + `init_db()`
- `app/models/__init__.py` — Student, Project, DailyPlan, GithubActivity, Assessment, ScoringConfig
- `app/database.py` — SQLite 引擎 + `get_session()` 生成器

### Iter 2 — 导入服务（1 个文件，17 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 2.1 | 导入学生/项目/计划 | `app/services/import_service.py` | `tests/unit/test_import.py` | 17 | ✅ |

**实际产出：**
- `app/services/import_service.py` — `import_students()`, `import_projects()`, `import_daily_plans()`
- 支持中英列名映射，缺必填列时 raise ValueError

### Iter 3 — GitHub 同步服务（2 个文件，24 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 3.1 | GitHub API 封装 | `app/services/github_service.py` | `tests/unit/test_github.py` | 17 | ✅ |
| 3.2 | 批量同步落库 | `app/services/github_snapshot.py` | `tests/unit/test_github_snapshot.py` | 7 | ✅ |

**实际产出：**
- `app/services/github_service.py` — `fetch_activity(repo, date, github_token)` + 异常类
- `app/services/github_snapshot.py` — `sync_day(target_date, session)`

### Iter 4 — AI 评分服务 + 重试机制（3 个文件，34 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 4.1 | LLM 评分 | `app/services/ai_scoring_service.py` | `tests/unit/test_ai_scoring.py` | 29 | ✅ |
| 4.2 | 重试服务 | `app/services/retry_service.py` | `tests/unit/test_retry.py` | 5 | ✅ |
| 4.3 | 上下文裁剪 + 校验 | 同上 | 同上 | 含于 29 个用例 | ✅ |

**实际产出：**
- `app/services/ai_scoring_service.py` — `score_student(context, settings)`，含上下文裁剪和响应校验
- `app/services/retry_service.py` — `retry_failed_assessments(session)`，含 3 次指数退避重试

### Iter 5 — 评分引擎 + 评测流水线（2 个文件，15 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 5.1 | 权重算分 | `app/services/scoring_engine.py` | `tests/unit/test_scoring_engine.py` | 6 | ✅ |
| 5.2 | 评测流水线 | `app/services/pipeline.py` | `tests/unit/test_pipeline.py` | 9 | ✅ |

**实际产出：**
- `app/services/scoring_engine.py` — `compute_final(subscores, config)` 纯函数
- `app/services/pipeline.py` — `run_today(target_date, session)` 串联全流程

### Iter 6 — 邮件服务（1 个文件，11 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 6.1 | 邮件发送 | `app/services/email_service.py` | `tests/unit/test_email.py` | 7 | ✅ |
| 6.2 | 集成：流水线不退回邮件失败 | — | `tests/integration/test_run_today_email.py` | 4 | ✅ |

**实际产出：**
- `app/services/email_service.py` — `send_daily_comments(target_date, session)`
- 邮件服务异常被 pipeline catch，不影响评分结果

### Iter 7 — API 路由 + 导出 + 配置种子（4 个文件，36 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 7.1 | API 路由 | `app/api/routes.py` | `tests/integration/test_routes.py` | 24 | ✅ |
| 7.2 | 导出工具 | `app/utils/export.py` | `tests/unit/test_export.py` | 6 | ✅ |
| 7.3 | 配置种子 | `app/services/config_seed.py` | `tests/unit/test_config_seed.py` | 3 | ✅ |
| 7.4 | 认证中间件 | `app/middleware/auth.py` | `tests/integration/test_auth_schedule.py`（含） | 含 8 个用例 | ✅ |

**实际产出：**
- `app/api/routes.py` — 所有路由：`GET /`, `/students`, `/projects`, `/plans`, `/config`, `/results`, `/export`, `POST /run-today`
- `app/utils/export.py` — `export_daily(date, session) -> bytes`
- `app/services/config_seed.py` — `seed_config(session)` 幂等初始化
- `app/middleware/auth.py` — `require_auth()`, `login_endpoint()`

### Iter 8 — Web UI + 启动入口（3 个文件，8 个测试）

| 顺序 | 任务 | 实际文件 | 测试文件 | 测试数 | 状态 |
|------|------|---------|---------|--------|------|
| 8.1 | FastAPI 入口 | `app/main.py` | `tests/integration/test_routes.py`（含） | 含 8 个页面测试 | ✅ |
| 8.2 | Jinja2 模板 | `app/templates/*.html` | 手动验证 | — | ✅ |
| 8.3 | 定时调度器 | `app/scheduler.py` | `tests/integration/test_auth_schedule.py` | 2 | ✅ |

**实际产出：**
- `app/main.py` — FastAPI 应用，挂载路由、静态文件、Jinja2 模板
- `app/templates/` — `base.html`, `index.html`, `students.html`, `projects.html`, `plans.html`, `config.html`, `results.html`
- `app/scheduler.py` — APScheduler 后台任务，由 `AUTO_RUN_TIME` 驱动

---

## 依赖链

```
Iter 0（工程基础）
  ↓
Iter 1（配置 + 模型）→ 独立，无项目内依赖
  ↓
Iter 2（导入服务）→ 依赖 Iter 1
  ↓
Iter 3（GitHub 服务）→ 依赖 Iter 1
  ↓
Iter 4（AI 评分）→ 依赖 Iter 1
  ↓
Iter 5（评分引擎 + 流水线）→ 依赖 Iter 1+3+4
  ↓
Iter 6（邮件服务）→ 依赖 Iter 1
  ↓
Iter 7（API 路由 + 导出）→ 依赖 Iter 1+2+4+5+6
  ↓
Iter 8（Web UI）→ 依赖全部
```

---

## 文件清单（实际）

### 应用代码（18 个文件）

| 文件 | 行数 | 说明 |
|------|------|------|
| `app/config/__init__.py` | 64 | 配置读取 |
| `app/models/__init__.py` | 107 | 数据模型 |
| `app/database.py` | 14 | 数据库连接 |
| `app/services/import_service.py` | 150 | 导入服务 |
| `app/services/github_service.py` | 103 | GitHub API |
| `app/services/github_snapshot.py` | 71 | 批量同步 |
| `app/services/ai_scoring_service.py` | 163 | AI 评分 |
| `app/services/scoring_engine.py` | 37 | 权重算分 |
| `app/services/pipeline.py` | 158 | 评测流水线 |
| `app/services/email_service.py` | 148 | 邮件服务 |
| `app/services/retry_service.py` | 124 | 重试服务 |
| `app/services/config_seed.py` | 31 | 配置种子 |
| `app/api/routes.py` | 132 | API 路由 |
| `app/utils/export.py` | 55 | 导出工具 |
| `app/middleware/auth.py` | 38 | 认证中间件 |
| `app/main.py` | 9 | 应用入口 |
| `app/scheduler.py` | 37 | 定时调度 |
| `app/__init__.py` | 0 | 包声明 |

### 模板（7 个文件）

| 文件 | 行数 |
|------|------|
| `app/templates/base.html` | 48 |
| `app/templates/index.html` | 50 |
| `app/templates/students.html` | 36 |
| `app/templates/projects.html` | 27 |
| `app/templates/plans.html` | 27 |
| `app/templates/config.html` | 35 |
| `app/templates/results.html` | 44 |

### 测试代码（15 个文件，165 个用例）

| 文件 | 测试数 | 类型 |
|------|--------|------|
| `tests/unit/test_ai_scoring.py` | 29 | 单元测试 |
| `tests/unit/test_config.py` | 8 | 单元测试 |
| `tests/unit/test_config_seed.py` | 3 | 单元测试 |
| `tests/unit/test_email.py` | 7 | 单元测试 |
| `tests/unit/test_export.py` | 6 | 单元测试 |
| `tests/unit/test_github.py` | 17 | 单元测试 |
| `tests/unit/test_github_snapshot.py` | 7 | 单元测试 |
| `tests/unit/test_import.py` | 17 | 单元测试 |
| `tests/unit/test_models.py` | 15 | 单元测试 |
| `tests/unit/test_pipeline.py` | 9 | 单元测试 |
| `tests/unit/test_retry.py` | 5 | 单元测试 |
| `tests/unit/test_scoring_engine.py` | 6 | 单元测试 |
| `tests/integration/test_auth_schedule.py` | 8 | 集成测试 |
| `tests/integration/test_routes.py` | 24 | 集成测试 |
| `tests/integration/test_run_today_email.py` | 4 | 集成测试 |
| `tests/conftest.py` | — | Fixtures |

---

## 里程碑

| M1 | 配置 + 模型全绿 | Iter 1 完成 | ✅ |
| M2 | 导入服务可用 | Iter 2 完成 | ✅ |
| M3 | GitHub 同步正常 | Iter 3 完成 | ✅ |
| M4 | AI 评分 + 重试通过 | Iter 4 完成 | ✅ |
| M5 | 评分引擎 + 流水线测试通过 | Iter 5 完成 | ✅ |
| M6 | 邮件发送正常 | Iter 6 完成 | ✅ |
| M7 | API 接口全部覆盖 | Iter 7 完成 | ✅ |
| M8 | Web UI 可用，端到端验证 | ✅ 全部完成 | ✅ |

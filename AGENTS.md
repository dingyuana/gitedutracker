# 学生 GitHub 日报追踪器 — AGENTS（开发者速查）

> 本文档面向未来进入本项目的 AI agent / 人类开发者，读完即可复现环境并开展开发。

---

## 一、快速启动

```bash
cd /data/disk/gitedutracker

# 1. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入必填项（见第二节）

# 4. 初始化数据库
.venv/bin/python -c "from app.database import init_db; init_db()"

# 5. 启动服务（开发热重载）
.venv/bin/uvicorn app.main:app --reload --port 8000
```

启动后访问 `http://localhost:8000`。

---

## 二、.env 必填项

> **注意**：开发/测试环境不需要真实 token，测试中已 mock。但生产运行必须配置。

| 变量 | 说明 | 示例 |
|------|------|------|
| `GITHUB_TOKEN` | GitHub Personal Access Token（需 repo 权限） | `ghp_xxxxxxxxxxxx` |
| `LLM_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.openai.com/v1` |
| `LLM_API_KEY` | LLM API Key | `sk-xxxxxxxx` |
| `LLM_MODEL` | 模型名称 | `gpt-4o-mini` |
| `LLM_CONTEXT_MAX_CHARS` | 上下文最大字符数（默认 12000） | `12000` |
| `SMTP_HOST` | SMTP 服务器 | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP 端口 | `587` |
| `SMTP_USER` | 发件邮箱 | `your@gmail.com` |
| `SMTP_PASS` | 邮箱授权码 | `xxxxxxxx` |
| `SMTP_FROM` | 发件人显示名/邮箱 | `your@gmail.com` |
| `ADMIN_PASSWORD` | Web UI 管理密码（留空=无登录） | `change_me` |
| `AUTO_RUN_TIME` | 定时评测 cron 表达式（可选） | `0 9 * * *` |
| `DATABASE_URL` | SQLite 路径（默认 ./data/github_tracker.db） | `sqlite:///./data/github_tracker.db` |
| `TZ` | 时区（默认 Asia/Shanghai，GitHub API 需 UTC） | `Asia/Shanghai` |

> 所有密钥必须来自 `.env`，禁止硬编码到代码中。

---

## 三、导入/导出列约定

### 学生表（students.xlsx）
| 列名 | 说明 |
|------|------|
| 学生姓名 | 学生真实姓名 |
| 邮箱 | 用于发送评估邮件 |
| github仓库 | GitHub 仓库完整 URL，如 `https://github.com/user/repo` |

### 项目表（projects.xlsx）
| 列名 | 说明 |
|------|------|
| 项目ID | 唯一标识 |
| 项目名称 | 项目显示名 |
| Git仓库URL | 完整 Git URL |

### 计划表（daily_plans.xlsx）
| 列名 | 说明 |
|------|------|
| 日期 | 格式 `YYYY-MM-DD` |
| 项目名称 | 关联项目表 |
| 工作计划 | 当日预期任务描述 |
| 学生姓名 | 可选，留空表示适用于所有学生 |

---

## 四、一键「今日评测」

**Web UI 方式：**
打开 `http://localhost:8000`，点击首页「今日评测」按钮。

**API 方式：**
```bash
curl -X POST "http://localhost:8000/run-today?date=2025-01-15"
```

评测流程（内部串联）：
1. GitHub 同步 — 获取各仓库当日 commits / PRs / LOC
2. AI 评分 — 调用 LLM 生成四维评分（代码量/代码质量/任务匹配/进度状态）+ 四段式评语
3. 权重算分 — 按 `ScoringConfig` 配置计算总分
4. 发送邮件 — 仅当显式要求时发送（默认不发，见下方「邮件发送策略」）
5. 导出结果 — 可下载当日 xlsx

### 启动方式：立即 / 定时（`EvalSchedule`）

项目评测面板（`/projects/{id}/eval`）的「启动方式」有两个选项：

| 选项 | 行为 |
|------|------|
| 立即手动开始 | 走 `start_eval_job()`，前台轮询进度条 |
| 指定时间自动启动 | 写一条 `EvalSchedule`（`status='pending'`），**默认次日 02:00** |

- `scheduler.py` 每 **1 分钟**轮询 `run_due_schedules()`，到点才执行；未到点的 `pending` 不动。
- 状态机：`pending → running → done / failed`；执行结果写 `result_json`。
- 单条计划失败**不阻断**其余计划（异常被捕获并落库）。
- 配合「仅未评测」范围即可实现「部分评测后，次日凌晨自动补齐未完成的」。

### 邮件发送策略（重要）

- **邮件正文永不包含任何分数，只发 AI 评语**。这是硬约束，`tests/unit/test_email.py::TestEmailNeverContainsScores` 会在 `_build_email` 源码里静态检查分数字段引用，改模板时不要往里加分。
- 分数只在 **Web 结果页** 与 **xlsx 导出** 展示（含四维分 + 加分 + 进度状态 + 进度调整）。
- 三种发送时机：
  1. 立即评测时勾选「完成后自动发送」
  2. 定时计划的 `auto_send_email=true`
  3. 事后手动：结果页「发送评语邮件」按钮 → `POST /send-emails?date=YYYY-MM-DD`
- 幂等：`email_sent=true` 的记录不会重复发送。

---

## 五、LLM 与 SMTP 配置

### LLM（OpenAI 兼容）
- 接口协议：`openai>=1.30.0` 客户端，兼容 AnyScale / 火山方舟 / DeepSeek 等
- 失败重试：最多 3 次，指数退避；仍失败则 persist `saved_context_json` + `next_retry_at`，2 小时后后台自动重试
- 上下文裁剪：`LLM_CONTEXT_MAX_CHARS` 控制最大字符数（默认 8000）

### SMTP 邮件
- 使用 Python 标准库 `smtplib`
- 支持 TLS（端口 587）
- 邮件内容模板：鼓励开头 + 今日成就 + 今日问题 + 改进建议
- **正文只含评语，绝不含分数**（详见第四节「邮件发送策略」）

### 失败重试分级（`retry_service`）

失败原因记录在 `Assessment.fail_reason`，重试间隔按原因区分：

| `fail_reason` | 触发场景 | 重试间隔 |
|---------------|----------|----------|
| `repo_pull` | 仓库镜像拉取/代码提取失败（`CodeExtractionError`） | **1 小时** |
| `llm` | LLM 3 次即时重试后仍失败 | **2 小时** |

- `attempts` 达到 `MAX_RETRY_ATTEMPTS = 5` 后置为 `needs_manual`，不再自动重试（避免无效仓库无限重试）。
- `scheduler.py` 每 **1 小时**调用 `reap_due()`；此 job 的注册**不依赖 `AUTO_RUN_TIME`**（历史缺陷：该变量为空曾导致整个调度器不启动，重试永不触发）。

---

## 六、测试命令

```bash
# 运行全部测试
.venv/bin/pytest

# 仅运行单元测试（mock 外部依赖，速度快）
.venv/bin/pytest tests/unit/ -v

# 运行集成测试
.venv/bin/pytest tests/integration/ -v

# 运行单个测试文件
.venv/bin/pytest tests/unit/test_scoring_engine.py -v

# 带覆盖率
.venv/bin/pytest --cov=app --cov-report=term-missing
```

**测试约定：**
- 外部依赖（GitHub API、LLM、SMTP）必须 mock，禁止在测试中调用真实服务
- fixtures 集中在 `tests/conftest.py`，使用 SQLite in-memory 数据库
- **`tests/conftest.py` 会 mock `openai` 模块**，因此测试可导入 `ai_scoring_service` 而无需真实 openai 包
- TDD：每个新特性先写 RED 测试，再实现 GREEN
- **Assessment 幂等键**：`(student_id, project_id, date)`，重复运行 `run_today` 会更新而非重复创建

---

## 七、架构分层

```
app/
├── config/        # 纯配置：从 .env 读取，无项目内依赖
├── utils/         # 纯工具函数：export.py 等，无项目内依赖
├── models/        # SQLModel 数据模型，依赖 config
├── services/      # 业务逻辑，依赖 models + utils
│   ├── import_service.py    # 导入 xlsx
│   ├── github_service.py    # GitHub 活动同步
│   ├── ai_scoring_service.py # LLM 评分 + 重试
│   ├── scoring_engine.py    # 权重算分（纯函数）
│   ├── pipeline.py          # 评测流水线串联
│   ├── schedule_service.py  # 定时评测计划（EvalSchedule）
│   ├── retry_service.py     # 失败重试 reaper（按 fail_reason 分级）
│   └── email_service.py     # 邮件发送
├── api/           # HTTP 路由，依赖 services
│   └── routes.py
├── templates/     # Jinja2 模板
├── static/        # 静态资源
├── scheduler.py   # APScheduler：日常评测 + 重试(1h) + 定时计划轮询(1min)
├── database.py    # 数据库连接 + init_db()（含 SQLite 列迁移）
└── main.py        # FastAPI 应用入口

scripts/
└── backfill_scores.py  # 一次性回填历史分数字段（见下）
```

**依赖方向（单向）：** `app → api → services → models → config / utils`

**禁止：** 跨层调用（api 不得直接访问 models）、吞异常（空 except / pass）、硬编码密钥。

---

## 十、关键实现细节（易错点）

### 时区处理
- 教师本地时区默认 `Asia/Shanghai`（D24）
- GitHub API 的 `since`/`until` 参数必须是 **UTC**
- `app/services/github_service.py` 中的 `_date_to_utc_range()` 负责转换

### LLM 失败重试
- 单次调用最多 3 次，指数退避（1s, 2s）
- 3 次全败 → `Assessment.status='failed'`，`fail_reason='llm'`，`next_retry_at = now + 2h`，保存 `saved_context_json`
- 仓库拉取失败（`CodeExtractionError`）→ `fail_reason='repo_pull'`，`next_retry_at = now + 1h`
- 后台 `retry_service.reap_due()` 每 **1 小时**扫描到期失败项（间隔由 `fail_reason` 决定，不是扫描频率）
- `attempts >= 5` 后转 `needs_manual`，停止自动重试
- `LLMInvalidResponse` 异常在 `pipeline.py` 中被捕获，不影响其他学生

### 分数字段回写（易漏）

`Assessment` 有 6 个分数字段，**每条评分路径都必须写全**：

| 字段 | 来源 |
|------|------|
| `quality_score` / `match_score` / `bonus_score` | LLM 直接返回 |
| `volume_score` | `scoring_engine.derive_volume_score()` |
| `schedule_adjustment` | `scoring_engine.derive_schedule_adjustment()` |
| `total_score` | `scoring_engine.compute_final()` |

- 共 **3 处**写入点：`pipeline.py` 的 diff 路径、`pipeline.py` 的 full 路径、`retry_service.py` 的重试成功路径。改动其一时三处都要同步。
- 历史缺陷：`volume_score` / `schedule_adjustment` 曾在三处**全部漏写**，导致 280 条记录该字段为 NULL/0，但值已计入 `total_score`。已由 `scripts/backfill_scores.py` 从 `total_score` 代数反解回填。
- 推导公式只允许存在于 `scoring_engine.py`，不要在调用方就地重算。

### 数据库备份（SQLite WAL）

本库运行在 **WAL 模式**，`cp xxx.db` 会漏掉 `-wal` 中尚未 checkpoint 的已提交数据，得到静默残缺的副本。

```python
# 正确做法：官方 backup API
import sqlite3
src = sqlite3.connect('data/github_tracker.db')
dst = sqlite3.connect('/tmp/backup.db')
with dst:
    src.backup(dst)
```

### 邮件发送
- 同一学生当日多条 Assessment（多项目）汇总为**一封邮件**（D25）
- 邮件失败不阻塞评分结果，仅记录 warning 日志
- 已发送邮件（`email_sent=true`）不重复发送
- **正文只含评语，不含任何分数**（硬约束，有测试锁定）

### 导入列名别名
- 学生表：`学生姓名`/`student_name` → `name`，`GitHub仓库`/`github_repo`/`仓库地址` → `github_repo`，`邮箱`/`email` → `email`
- 项目表：`项目名称`/`project_name` → `name`
- 计划表：`日期`/`date`，`项目名称`/`project_name` → 查找 project_id，`工作计划`/`plan_content` → `content`，`学生姓名`/`student_name` → 查找 student_id（可选）

---

## 八、Spec-Coding 约定入口

本项目采用 **SPEC / PLAN / AGENT 三件套** 驱动开发：

| 文件 | 作用 |
|------|------|
| `SPEC.md` | 全局契约：所有场景（Scenario）+ 各迭代实现范围 + 验收标准 |
| `PLAN.md` | 迭代计划：每个 Iter 的任务清单、顺序、依赖链 |
| `AGENT.md` | 编码规范：命名、分层、禁止项、响应格式、TDD 红线 |

**迭代开发流程（每次新增功能必读）：**
1. 在 `SPEC.md` 中确认目标 Scenario
2. 在 `PLAN.md` 中找到对应 Iter 的任务清单
3. 阅读 `AGENT.md` 确认规范约束
4. **先写测试（RED）** → `tests/unit/test_xxx.py`
5. **再写代码（GREEN）** → 对应 `app/services/` 或 `app/models/`
6. 跑通测试后 commit：`feat: Iter N - 描述`
7. 每个 Iter 新增文件 ≤ 3 个

---

## 九、常用路径速查

| 内容 | 路径 |
|------|------|
| 启动入口 | `app/main.py` |
| 配置读取 | `app/config/__init__.py` |
| 数据模型 | `app/models/__init__.py` |
| 数据库初始化 | `app/database.py` |
| 导入服务 | `app/services/import_service.py` |
| GitHub 同步 | `app/services/github_service.py` |
| AI 评分 | `app/services/ai_scoring_service.py` |
| 评分引擎 | `app/services/scoring_engine.py` |
| 评测流水线 | `app/services/pipeline.py` |
| 定时评测计划 | `app/services/schedule_service.py` |
| 失败重试 reaper | `app/services/retry_service.py` |
| 定时调度注册 | `app/scheduler.py` |
| 邮件服务 | `app/services/email_service.py` |
| API 路由 | `app/api/routes.py` |
| 导出工具 | `app/utils/export.py` |
| 分数回填脚本 | `scripts/backfill_scores.py` |
| 单元测试 | `tests/unit/` |
| 集成测试 | `tests/integration/` |
| 公共 fixtures | `tests/conftest.py` |

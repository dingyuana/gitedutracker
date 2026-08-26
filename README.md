# 学生 GitHub 日报追踪器

> AI 驱动的学生 GitHub 仓库每日评测系统——导入学生仓库、项目与计划，一键自动生成评分与鼓励性评语邮件。

[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLModel](https://img.shields.io/badge/orm-SQLModel-ff69b4.svg)](https://sqlmodel.tiangolo.com/)
[![pytest](https://img.shields.io/badge/tests-165%20passed-brightgreen.svg)](https://pytest.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 功能概览

| 功能 | 说明 |
|------|------|
| 📥 **三表导入** | 学生（含邮箱+仓库，可归属项目）、项目、每日计划，支持中英文列名 |
| 👥 **项目分组** | 学生归属项目，计划/评测按项目隔离，不同项目互不串评 |
| 🗓️ **项目看板** | 首页即管理台：新建/编辑/**完成**/重开/删除项目；点卡片进日程详情 |
| 🔍 **评语查询** | 每日分数与 AI 评语按项目、按日期归档，随时回查 |
| ⚙️ **LLM 前端可配** | 模型名 / Base URL / API Key / 上下文长度在「配置」页修改，立即生效（DB 优先于 .env） |
| 🛠️ **项目管理** | 新增、编辑、删除项目（名称/描述/起止日期） |
| 📅 **计划管理** | 新增、编辑、删除每日计划（日期/项目/内容/指定学生） |
| 🔄 **GitHub 同步** | 每日抓取 commits / PRs / 代码行数（additions/deletions） |
| 🤖 **AI 自动评分** | 四维评分：代码量、质量、任务匹配度、进度状态 |
| 🎛️ **评测面板** | 首页可选日期与范围：仅未测评 / 全部重评，评完自动跳转结果页 |
| 📈 **分数趋势图** | 每日平均分 + 每个学生分数变化折线（SVG 零依赖，离线可用） |
| ⏱️ **同步节流** | 全班仓库抓取自动限速，规避 GitHub 反滥用限流 |
| ✉️ **鼓励邮件** | 自动发送四段式评语邮件（成果 + 问题 + 建议） |
| 📊 **导出 xlsx** | 一键导出每日评分表 + 评语 |
| 🕐 **定时调度** | 可选 `AUTO_RUN_TIME` 每日自动运行 |
| 🔐 **可选登录** | 配置 `ADMIN_PASSWORD` 启用基础认证 |
| 🔄 **LLM 重试** | 失败 3 次后落库，2 小时后台自动重试 |

---

## 快速启动

```bash
cd /data/disk/gitedutracker

# 1. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入必填项（见下方配置说明）

# 4. 初始化数据库
.venv/bin/python -c "from app.database import init_db; init_db()"

# 5. 启动服务
.venv/bin/uvicorn app.main:app --reload --port 8000
```

访问 `http://localhost:8000`，点击首页「今日评测」按钮即可开始。

---

## 环境配置（.env）

> 开发/测试环境不需要真实 token，测试中已 mock。生产运行必须配置。

| 变量 | 说明 | 必填 | 示例 |
|------|------|------|------|
| `GITHUB_TOKEN` | GitHub PAT（需 repo 权限） | ✅ | `ghp_xxxxxxxxxxxx` |
| `LLM_BASE_URL` | OpenAI 兼容 API 地址 | ✅ | `https://api.openai.com/v1` |
| `LLM_API_KEY` | LLM API Key | ✅ | `sk-xxxxxxxx` |
| `LLM_MODEL` | 模型名称 | ✅ | `gpt-4o-mini` |
| `LLM_CONTEXT_MAX_CHARS` | 上下文最大字符数 | ❌ | `12000` |
| `SMTP_HOST` | SMTP 服务器 | ✅ | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP 端口 | ❌ | `587` |
| `SMTP_USER` | 发件邮箱 | ✅ | `your@gmail.com` |
| `SMTP_PASS` | 邮箱授权码 | ✅ | `xxxxxxxx` |
| `SMTP_FROM` | 发件人显示名 | ❌ | `your@gmail.com` |
| `ADMIN_PASSWORD` | Web UI 管理密码 | ❌ | `change_me` |
| `AUTO_RUN_TIME` | 定时评测 cron 表达式 | ❌ | `0 9 * * *` |
| `DATABASE_URL` | SQLite 路径 | ❌ | `sqlite:///./data/github_tracker.db` |
| `TZ` | 时区 | ❌ | `Asia/Shanghai` |

---

## 导入格式

### 学生表（students.xlsx）

| 列名（中英文均可） | 说明 |
|-----------------|------|
| 学生姓名 / student_name | 学生真实姓名 |
| 邮箱 / email | 用于发送评估邮件 |
| GitHub仓库 / github_repo | 完整 URL 或 owner/repo 格式 |

### 项目表（projects.xlsx）

| 列名 | 说明 |
|------|------|
| 项目名称 / project_name | 项目显示名 |
| 描述 / description | 可选 |
| 开始日期 / start_date | 可选 |
| 结束日期 / end_date | 可选 |

### 计划表（daily_plans.xlsx）

| 列名 | 说明 |
|------|------|
| 日期 / date | 格式 `YYYY-MM-DD` |
| 项目名称 / project_name | 关联项目表 |
| 工作计划 / plan_content | 当日预期任务描述 |
| 学生姓名 / student_name | 可选，留空表示适用于所有学生 |

---

## 一键「今日评测」流程

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  GitHub 同步 │ → │  AI 四维评分  │ → │  权重算分    │
│ commits/PRs │    │ 质量/匹配/进度│    │  总分计算    │
└─────────────┘    └──────────────┘    └──────┬──────┘
                                              │
                    ┌─────────────────────────┘
                    ▼
         ┌──────────────────────┐
         │  自动发邮件 + 导出 xlsx │
         └──────────────────────┘
```

### API 调用

```bash
# Web UI 方式：打开 http://localhost:8000，点击「今日评测」

# API 方式
curl -X POST "http://localhost:8000/run-today?date=2026-08-21"
# 返回：{"success": 2, "failed": 0, "details": [...]}
```

---

## 架构分层

```
app/
├── main.py              # FastAPI 应用入口
├── config/              # 配置（.env 读取）
├── utils/               # 工具函数（xlsx 导出）
├── models/              # SQLModel 数据模型
│   ├── Student
│   ├── Project
│   ├── DailyPlan
│   ├── GithubActivity
│   ├── Assessment
│   └── ScoringConfig
├── services/            # 业务逻辑
│   ├── import_service.py    # 导入 xlsx
│   ├── github_service.py    # GitHub 活动同步
│   ├── github_snapshot.py   # 快照落库
│   ├── ai_scoring_service.py # LLM 评分 + 重试
│   ├── scoring_engine.py    # 权重算分（纯函数）
│   ├── pipeline.py          # 评测流水线串联
│   ├── retry_service.py     # 后台重试 reaper
│   ├── email_service.py     # 邮件发送
│   ├── config_seed.py       # 默认权重种子
│   └── settings_service.py  # LLM 配置（DB 优先于 .env）
├── api/                 # HTTP 路由
│   └── routes.py
├── middleware/          # 认证中间件
│   └── auth.py
├── scheduler.py         # APScheduler 定时任务
├── database.py          # 数据库连接
├── templates/           # Jinja2 模板
│   ├── base.html        # 全局布局 + 样式（现代仪表盘风）
│   ├── index.html       # 项目看板（含新建/编辑/完成/删除）
│   ├── project_detail.html  # 项目日程与评语查询
│   ├── students.html    # 学生列表 + 导入（支持归属项目）
│   ├── plans.html       # 计划列表
│   ├── config.html      # 权重与 LLM 配置
│   └── results.html     # 评测结果
└── static/              # 静态资源
```

**依赖方向（单向）：**
```
main → api/middleware/scheduler → services → models → config / utils
```

---

## 测试

```bash
# 运行全部测试（165 个）
.venv/bin/pytest

# 仅运行单元测试（mock 外部依赖）
.venv/bin/pytest tests/unit/ -v

# 运行集成测试
.venv/bin/pytest tests/integration/ -v

# 单个测试文件
.venv/bin/pytest tests/unit/test_scoring_engine.py -v

# 带覆盖率
.venv/bin/pytest --cov=app --cov-report=term-missing
```

**测试约定：**
- 外部依赖（GitHub API、LLM、SMTP）必须 mock
- `tests/conftest.py` 提供公共 fixtures（SQLite in-memory）
- TDD：每个新特性先写 RED 测试，再实现 GREEN

---

## 关键设计决策

| 决策 | 说明 |
|------|------|
| **AI 全自动评分** | 无教师复核环节，AI 生成四维评分 + 四段评语 |
| **LLM 重试策略** | 3 次即时重试 → 失败后落库 + 2 小时后台重试 |
| **Assessment 幂等键** | `(student_id, project_id, date)`，重复运行更新而非重复创建 |
| **时区处理** | 教师本地 Asia/Shanghai → GitHub API 的 UTC 查询 |
| **多项目邮件聚合** | 同一学生当日多条 Assessment 合并为一封邮件 |
| **diff 上下文截断** | 超 `LLM_CONTEXT_MAX_CHARS` 时只保留 message + stats |

---

## 开发规范

本项目采用 **spec-coding 三件套** 驱动开发：

| 文件 | 作用 |
|------|------|
| `SPEC.md` | 全局契约：场景 + 迭代范围 + 验收标准 |
| `PLAN.md` | 迭代计划：任务清单、顺序、依赖链 |
| `AGENT.md` | 编码规范：命名、分层、禁止项、TDD 红线 |

**迭代流程：**
1. 在 `SPEC.md` 中确认目标 Scenario
2. 在 `PLAN.md` 中找到对应 Iter
3. **先写测试（RED）** → `tests/unit/test_xxx.py`
4. **再写代码（GREEN）** → `app/services/` 或 `app/models/`
5. 跑通测试后 commit：`feat: Iter N - 描述`
6. 每 Iter 新增文件 ≤ 3 个

---

## 路径速查

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
| 邮件服务 | `app/services/email_service.py` |
| API 路由 | `app/api/routes.py` |
| 导出工具 | `app/utils/export.py` |
| 单元测试 | `tests/unit/` |
| 集成测试 | `tests/integration/` |
| 公共 fixtures | `tests/conftest.py` |
| 样例数据 | `tests/fixtures/` |

---

## 技术栈

- **后端框架**: FastAPI
- **ORM**: SQLModel + SQLite
- **GitHub API**: PyGithub
- **LLM 客户端**: OpenAI SDK（兼容任意 OpenAI 接口）
- **邮件发送**: Python smtplib
- **Excel 处理**: pandas + openpyxl
- **定时调度**: APScheduler
- **前端模板**: Jinja2 + HTMX
- **测试框架**: pytest + unittest.mock

---

## 许可证

MIT License

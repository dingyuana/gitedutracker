# 学生 GitHub 日报追踪器 — PLAN

## 迭代规划

### Iter 0 — 工程基础（无代码）

| 任务 | 产出 | 状态 |
|------|------|------|
| SPEC.md | 全局 SPEC（定义所有迭代范围 + 验收表） | ⬜ |
| PLAN.md | 本文件 | ⬜ |
| AGENT.md | 编码规范（Python 命名 + 分层 + 禁止项） | ⬜ |
| .env.example | 环境变量模板 | ⬜ |
| requirements.txt | 项目依赖声明 | ⬜ |
| .gitignore | 忽略规则 | ⬜ |

### Iter 1 — 配置 + 数据模型（3 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 1.1 | SPEC: 配置 + 模型 | 定义 config/index.py 和 models/ 所有 SQLModel |
| 1.2 | 测试: `tests/unit/test_config.py` | TDD RED |
| 1.3 | 代码: `app/config/__init__.py` | 配置读取 |
| 1.4 | 测试: `tests/unit/test_models.py` | TDD RED |
| 1.5 | 代码: `app/models/__init__.py` | 所有数据模型 |

### Iter 2 — 数据库初始化 + 导入服务（2 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 2.1 | SPEC: 导入服务 | 定义 import_service.py 接口 |
| 2.2 | 代码: `app/services/import_service.py` | pandas + openpyxl 读取 xlsx |
| 2.3 | 测试: `tests/unit/test_import_service.py` | TDD RED → GREEN（mock pandas） |
| 2.4 | 代码: `app/database.py` | SQLite 连接 + 建表 |

### Iter 3 — GitHub 同步服务（1 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 3.1 | SPEC: GitHub 服务 | 定义 github_service.py 接口 |
| 3.2 | 测试: `tests/unit/test_github_service.py` | TDD RED（mock PyGithub） |
| 3.3 | 代码: `app/services/github_service.py` | GREEN |

### Iter 4 — AI 评分服务 + 重试机制（2 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 4.1 | SPEC: AI 评分服务 | 定义 ai_scoring_service.py 接口 |
| 4.2 | 测试: `tests/unit/test_ai_scoring_service.py` | TDD RED（mock openai） |
| 4.3 | 代码: `app/services/ai_scoring_service.py` | GREEN（含重试逻辑） |
| 4.4 | 测试: `tests/unit/test_retry.py` | 重试策略测试 |

### Iter 5 — 评分引擎 + 评测流水线（2 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 5.1 | SPEC: 评分引擎 | 定义 scoring_engine.py 纯函数接口 |
| 5.2 | 测试: `tests/unit/test_scoring_engine.py` | TDD RED |
| 5.3 | 代码: `app/services/scoring_engine.py` | GREEN |
| 5.4 | 代码: `app/services/pipeline.py` | 串联 github → ai → scoring |

### Iter 6 — 邮件服务（1 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 6.1 | SPEC: 邮件服务 | 定义 email_service.py 接口 |
| 6.2 | 测试: `tests/unit/test_email_service.py` | TDD RED（mock smtplib） |
| 6.3 | 代码: `app/services/email_service.py` | GREEN |

### Iter 7 — API 路由 + 导出（3 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 7.1 | SPEC: API 路由 | 定义 api/ 下所有路由接口 |
| 7.2 | 代码: `app/api/import_routes.py` | 导入接口 |
| 7.3 | 代码: `app/api/assess_routes.py` | 评测 + 导出接口 |
| 7.4 | 代码: `app/utils/export.py` | xlsx 导出工具 |
| 7.5 | 测试: `tests/integration/test_api.py` | 接口测试 |

### Iter 8 — Web UI + 启动入口（3 个文件）

| 顺序 | 任务 | 说明 |
|------|------|------|
| 8.1 | SPEC: Web UI | 定义模板结构和路由 |
| 8.2 | 代码: `app/app.py` | FastAPI 应用组装 |
| 8.3 | 代码: `app/templates/` | Jinja2 模板（index、import、assess） |
| 8.4 | 测试: 手动验证 | 浏览器打开验证 |

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
Iter 4（AI 评分）→ 依赖 Iter 1+3
  ↓
Iter 5（评分引擎 + 流水线）→ 依赖 Iter 1+4
  ↓
Iter 6（邮件服务）→ 依赖 Iter 1
  ↓
Iter 7（API 路由）→ 依赖 Iter 2+4+5+6
  ↓
Iter 8（Web UI）→ 依赖全部
```

---

## 里程碑

| M1 | 配置 + 模型全绿 | Iter 1 完成 |
| M2 | 导入服务可用 | Iter 2 完成 |
| M3 | GitHub 同步正常 | Iter 3 完成 |
| M4 | AI 评分 + 重试通过 | Iter 4 完成 |
| M5 | 评分引擎 + 流水线测试通过 | Iter 5 完成 |
| M6 | 邮件发送正常 | Iter 6 完成 |
| M7 | API 接口全部覆盖 | Iter 7 完成 |
| M8 | Web UI 可用，端到端验证 | ✅ 全部完成 |

# 学生 GitHub 日报追踪器 — AGENT

## 命名规范

| 类型 | 风格 | 示例 |
|------|------|------|
| 变量 / 函数 | snake_case | `find_by_username`, `sync_activity` |
| 类 | PascalCase | `AppError`, `ScoringConfig` |
| 文件 / 目录 | kebab-case | `ai-scoring-service.py`（注意：Python 文件用下划线） |

**Python 文件命名使用 snake_case：**
- `import_service.py`
- `github_service.py`
- `ai_scoring_service.py`

## 分层规范（单向依赖）

```
config/     → 纯配置，从 .env 读取，不依赖项目内其他模块
utils/      → 纯工具函数（导出、格式化），不依赖项目内其他模块
models/     → 数据存取（SQLModel），依赖 config
services/   → 业务逻辑，依赖 models + utils
api/        → HTTP 路由 + 参数校验，依赖 services
app/        → 组装 FastAPI 应用 + 模板，依赖 api + services
```

**依赖方向：** `app → api → services → models → config / utils`

## 禁止事项

| 禁止 | 原因 |
|------|------|
| 吞异常（空 except 或 pass） | 必须 raise 或记录日志 |
| 密钥硬编码 | 所有密钥必须从 `.env` 读取 |
| 密码明文存储 | 必须 bcrypt 哈希（如有密码场景） |
| 硬编码邮箱 / 服务器地址 | 必须从 config 读取 |
| 在测试中调用真实 GitHub / LLM / SMTP | 必须 mock |
| 跨层调用（如 api 直接访问 models） | 必须经过 services |

## 响应格式

**成功 (200):**
```json
{ "success": true, "data": { ... } }
```

**异常 (400/401/404/500):**
```json
{ "error": "错误描述" }
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
- Mock 策略：GitHub API、LLM、SMTP 必须 mock
-  fixtures：使用 `conftest.py` 提供公共 fixtures（如 SQLite in-memory 数据库）
- 每个 Iter 的测试必须与代码同步推进（RED → GREEN）

## 迭代规则摘要

| 规则 | 说明 |
|------|------|
| 先测后码 | RED → GREEN，不得反向 |
| 单 Iter 文件数 | ≤ 3 个新增文件 |
| 门禁 | 上一 Iter 全绿后方可进入下一 Iter |
| 文档 | 全中文 |
| 禁止 | 不吞异常、密钥仅来自 .env、密码用 bcrypt |

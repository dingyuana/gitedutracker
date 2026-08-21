# student-github-tracker - Work Plan

> 本计划由 Prometheus 规划，依据 `.omo/drafts/student-github-tracker.md`（意图 CLEAR，review_required=false）。
> 开发方法遵循 spec-coding（SDD + TDD），参照本机 `/data/disk/spec-coding` 约定。
> 所有保存文档使用中文（D19）。

## TL;DR (For humans)
- **你会得到什么**：一个跑在老师本机的 FastAPI + SQLite Web 应用。老师一次性导入「学生(+邮箱)+GitHub仓库 / 项目 / 每日计划」三张表并配置 GitHub Token、LLM Key、SMTP 与评分权重后，点一下「今日评测」（或按 `AUTO_RUN_TIME` 定时），系统自动：同步各学生仓库当天活动（commits/PRs/代码行数/diff）→ AI 自动评出质量分、任务匹配分、计划完成情况+超前落后、四段式鼓励评语 → 按权重算总分 → 自动给每个学生发鼓励邮件 → 可导出「每日评分表+评语」xlsx。
- **为什么这样做**：需求明确要求「AI 全自动、无教师复核」「鼓励性评语含成果/问题/建议」「LLM 失败重试 3 次后落库并 2 小时再试」「spec coding 思想 + SDD/TDD」。故采用 AI 评分服务 + 失败队列 + 后台重试，并以 SPEC/PLAN/AGENT 三件套驱动 TDD 迭代。
- **它不会做**：不做教师人工复核界面（按需求取消）；不接第三方邮件服务（用标准 smtplib）；不做多租户/学生登录（单管理员本机）；质量分不靠魔法静态分析，而是 LLM 基于 diff 判断。
- **工作量**：约 9 个迭代（Iter 0 底座 + 8 个功能迭代），50+ 测试。
- **风险**：LLM 输出需严格 JSON 校验与失败重试（D22）；GitHub 速率/鉴权与 diff 体积需控制；SMTP 凭证由教师自备。
- **关键决策**：D1–D26（见草稿）。前端默认 Jinja2+HTMX 无构建（D5）；登录默认可选 `ADMIN_PASSWORD`（D6）；LLM 默认 OpenAI 兼容、推荐火山方舟 Doubao（D20）。

## Scope
**包含（IN）**
- 三张表 xlsx 导入（学生含邮箱与仓库、项目、每日计划），中文+英文列名兼容（D9）
- 每日 GitHub 同步：commits（含 diff/增删行）、PRs、代码行数快照（D10/D12）
- AI 自动评分四维：代码量（增删行）、质量、任务匹配、进度（超前/落后）（D12–D15）
- 四段式鼓励评语自动生成（鼓励开场+成果+问题+建议）（D18）
- 评分引擎按教师配置权重 + 进度加减分算总分（D16）
- 评测后自动发鼓励邮件（smtplib + 教师 SMTP）（D17）
- LLM 失败：重试 3 次→落库+2 小时后台重试，不静默丢弃（D22）
- 一键「今日评测」+ 可选 `AUTO_RUN_TIME` 定时（D21）
- 导出每日评分表+评语 xlsx（D8）
- 项目自带 SPEC.md / PLAN.md / AGENT.md（中文）+ 本仓库 AGENTS.md（D19/D23）
- 全程 TDD（pytest，RED→GREEN），GitHub/LLM/SMTP 全 mock（D7）

**不包含（OUT / Must-NOT-Have）**
- 教师人工复核/修改评分的 UI 环节（需求已取消）
- 学生端账号、多租户、部署到公网
- 第三方邮件 SaaS 集成
- 自动化代码质量静态分析工具链（质量分由 LLM 基于 diff 判断）
- 除 xlsx 外的其他导入格式（csv 仅作为可选，不强制）

## Verification strategy
- **TDD（tests-first）**：每个模块先写失败测试（RED）再实现（GREEN）；上一迭代全绿才进下一迭代（D7/D23）。
- **测试框架**：pytest；单元测试用 `unittest.mock` 模拟 GitHub(`PyGithub`)、LLM（OpenAI 兼容 client）、SMTP（`smtplib`）。
- **集成测试**：用 Fixture xlsx 验证导入/导出往返；用内存 SQLite 验证评分引擎与流水线编排。
- **失败注入**：专门测试 LLM 连续失败 → 触发 3 次重试 → 落库 `status=failed` + `next_retry_at`；后台 reaper 到点重试。
- **agent-executed QA**：每个 todo 含 happy + failure 场景与证据路径；不依赖人工判断。
- **全绿门禁**：`pytest` 全通过后该迭代方可提交并进入下一迭代。

## Execution strategy
- **spec-coding 三件套**：先写 `SPEC.md`（Given/When/Then 场景 + 各迭代接口契约 + 验收表）、`PLAN.md`（Iter 0 底座 → 迭代 SPEC→RED→GREEN）、`AGENT.md`（Python 命名与分层、禁止项、迭代规则），均中文。
- **分层（单向依赖）**：`config/` → `utils/` → `models/` → `services/` → `api/`(routes+controllers) → `app.py`；前端 `templates/` + `static/`（Jinja2+HTMX）。
- **迭代顺序（依赖链）**：Iter0 底座 → Iter1 模型/配置/DB → Iter2 表格导入导出 → Iter3 GitHub 同步 → Iter4 AI 评分服务+评分引擎 → Iter5 自动流水线+重试 reaper → Iter6 邮件 → Iter7 Web UI/调度 → Iter8 文档+AGENTS.md+全量验证。
- **每迭代 1–3 文件**，RED→GREEN，全绿提交。
- **配置即环境变量**：`.env`（GITHUB_TOKEN, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, SMTP_HOST/PORT/USER/PASS/FROM, ADMIN_PASSWORD, AUTO_RUN_TIME, DATABASE_URL）。

## Todos

### Iter 0 — 工程底座（无产品代码）
- [x] 1. SPEC/PLAN/AGENT 三件套骨架（中文）
  - References: D19, D23; `/data/disk/spec-coding/{SPEC,PLAN,AGENT}.md` 约定
  - Acceptance: 仓库根存在中文 `SPEC.md`(含项目场景与迭代契约框架)、`PLAN.md`(本迭代表)、`AGENT.md`(Python 命名/分层/禁止项)；内容为空壳待各迭代填充
  - QA happy: 打开三文件均存在且为 UTF-8 中文；failure: 缺任一文件则补齐
  - Commit: `git commit -m "docs: 初始化 SPEC/PLAN/AGENT 中文三件套"`

- [x] 2. 脚手架：requirements.txt / .env.example / .gitignore / app 包结构
  - References: D3,D4,D5,D6,D20,D21; C6
  - Acceptance: `requirements.txt` 含 fastapi, uvicorn, sqlmodel, pandas, openpyxl, pygithub, httpx(或 openai), pydantic-settings, jinja2, apscheduler(可选); `.env.example` 含全部变量模板；`.gitignore` 忽略 `.venv/`,`data/`,`.env`; `app/__init__.py` 与子包存在
  - QA happy: `pip install -r requirements.txt` 成功；failure: 缺关键依赖则补
  - Commit: `git commit -m "build: 脚手架与依赖声明"`

### Iter 1 — 数据模型 + 配置 + DB
- [x] 3. RED+GREEN：SQLModel 模型（Student/Project/DailyPlan/GithubActivity/PlanCompletion/Assessment/ScoringConfig）
  - References: D3,D9,D11,D12,D15,D16,D22; C1
  - Acceptance: `pytest tests/unit/test_models.py` 先红后绿；覆盖 Student(邮箱必填、仓库归一化 owner/repo)、Assessment(`status/attempts/next_retry_at/saved_context_json` 字段)、ScoringConfig 默认值
  - QA happy: 建 Student(含邮箱)→查回；建 Assessment 默认 status=pending；failure: 缺邮箱→校验失败；仓库 URL 归一化为 owner/repo
  - Commit: `git commit -m "feat: SQLModel 模型与 SQLite 引擎"`

- [x] 4. RED+GREEN：配置层（pydantic-settings 读 .env）+ DB 引擎初始化
  - References: D6,D20,D21; C1,C6
  - Acceptance: `pytest tests/unit/test_config.py` 红→绿；`get_settings()` 从 `.env` 读 GITHUB_TOKEN/LLM_*/SMTP_*/ADMIN_PASSWORD/AUTO_RUN_TIME；`init_db()` 创建表；`ADMIN_PASSWORD` 为空时 `require_auth=False`
  - QA happy: 提供 .env → 设置正确加载；failure: 缺 LLM_API_KEY → 启动评测时报明确错误而非崩溃
  - Commit: `git commit -m "feat: 配置层与数据库初始化"`

- [x] 5. RED+GREEN：ScoringConfig 种子（默认权重与加减分）
  - References: D16; C1
  - Acceptance: `pytest tests/unit/test_config_seed.py` 红→绿；`seed_config()` 幂等写入默认 w_volume/w_quality/w_match=各 1/3、loc_threshold、schedule_bonus/penalty；已存在则跳过
  - QA happy: 首次 seed 写入默认行；二次 seed 不重复创建；failure: 权重和≠1 时不强制但记录
  - Commit: `git commit -m "feat: ScoringConfig 默认种子（幂等）"`

### Iter 2 — 表格导入 / 导出
- [ ] 6. RED+GREEN：xlsx 导入引擎（学生/项目/计划，中英文列名别名）
  - References: D8,D9,D11; C2
  - Acceptance: `pytest tests/unit/test_import.py` 红→绿；用 fixture `tests/fixtures/sample_students.xlsx` 验证 `import_students()` 解析 学生姓名/ GitHub仓库(支持 URL 或 owner/repo)/ 邮箱(必填)；`import_projects()`、`import_plans()`（按 项目名称 解析 project_id，可选 学生姓名→student_id）
  - QA happy: 导入 3 行学生→DB 增 3；failure: 缺邮箱列→报错并指出行号；列名用「学生姓名」也能解析
  - Commit: `git commit -m "feat: xlsx 导入（中英文列名，学生/项目/计划）"`

- [ ] 7. RED+GREEN：xlsx 导出（每日评分表+评语）
  - References: D8,D18; C2
  - Acceptance: `pytest tests/unit/test_export.py` 红→绿；`export_daily(date)` 生成 xlsx，列含 日期,学生姓名,邮箱,GitHub仓库,项目名称,代码增,代码删,质量分,匹配分,进度,总分,评语；按日期过滤
  - QA happy: 造 2 条 Assessment → 导出 2 行且字段对齐；failure: 无数据→导出空表但格式正确
  - Commit: `git commit -m "feat: xlsx 导出每日评分表+评语"`

### Iter 3 — GitHub 同步
- [ ] 8. RED+GREEN：GitHub 客户端（PyGithub 封装，按仓库/日期取 commits+PRs+diff+增删行）
  - References: D1,D10,D12; C3
  - Acceptance: `pytest tests/unit/test_github.py` 红→绿；mock PyGithub，`fetch_activity(repo, date)` 返回 commits(count, list{sha,message,additions,deletions,files}), prs_opened, prs_merged, loc 汇总；仓库归一化；超界/空仓库优雅处理；`date` 按 D24 时区转 UTC 的 since/until 查询
  - QA happy: mock 返回 2 commits → 解析出 loc_additions/deletions；failure: 仓库不存在→抛可识别错误并记入状态
  - Commit: `git commit -m "feat: GitHub 客户端按日取活动与 diff"`

- [ ] 9. RED+GREEN：活动快照落库（GithubActivity）+ 批量同步入口
  - References: D10,D12; C3,C5
  - Acceptance: `pytest tests/unit/test_github_snapshot.py` 红→绿；`sync_day(date)` 为每个学生写/更新 `GithubActivity`（含 commits_json, loc, 状态, fetched_at）；按 D24 时区界定当日
  - QA happy: 2 学生 → 2 条快照；failure: 某学生仓库失败→其余成功，失败者状态标记
  - Commit: `git commit -m "feat: 每日 GitHub 活动快照落库"`

### Iter 4 — AI 评分服务 + 评分引擎
- [ ] 10. RED+GREEN：AI 评分服务（OpenAI 兼容调用，结构化 JSON，四段评语）
  - References: D13,D14,D15,D18,D20; C9
  - Acceptance: `pytest tests/unit/test_ai_scoring.py` 红→绿；mock LLM client，`score_student(context)` 返回 JSON{quality_score,match_score,completion(bool),schedule_status(enum),comment(四段中文),reasoning}；严格校验字段与枚举；校验失败视为 LLM 失败（触发重试）；context 含该项目当日计划文本(D25) 与仓库活动；diff 超 `LLM_CONTEXT_MAX_CHARS`(D26) 截断/摘要后再送
  - QA happy: mock 返回合法 JSON → 解析成功；failure: 返回非法 JSON / 缺字段 → 抛 `LLMInvalidResponse`
  - Commit: `git commit -m "feat: AI 评分服务（结构化 JSON 校验）"`

- [ ] 11. RED+GREEN：评分引擎（按权重+进度加减分算总分，纯函数）
  - References: D13,D14,D15,D16; C7
  - Acceptance: `pytest tests/unit/test_scoring_engine.py` 红→绿；`compute_final(subscores, config)` = w_volume*vol + w_quality*qual + w_match*match + schedule_adjustment；volume 由 loc 对照 loc_threshold 归一化；schedule_status→±bonus/penalty
  - QA happy: 各子分 80、权重均分、无加减 → 80；failure: 权重缺失→用默认；落后→总分被减分
  - Commit: `git commit -m "feat: 评分引擎（权重+进度加减分）"`

### Iter 5 — 自动流水线 + 失败重试
- [ ] 12. RED+GREEN：自动评分流水线（sync→AI→engine→persist Assessment）
  - References: D13,D14,D15,D18,D21; C5,C9
  - Acceptance: `pytest tests/unit/test_pipeline.py` 红→绿；`run_today()` 编排：同步→逐学生 AI 评分→算分→写 `Assessment(status=done, comment, scores)`→返回汇总；全程无人工环节；Assessment 以 (student_id,project_id,date) 为键(D25)，重跑幂等更新；对当日每个适用计划(学生专属或全员)分别评分
  - QA happy: mock GitHub+LLM → 生成 done 的 Assessment；failure: 单个学生 LLM 失败→不影响他人，该生进入重试队列
  - Commit: `git commit -m "feat: 自动评分流水线（无复核）"`

- [ ] 13. RED+GREEN：LLM 失败重试 + 2 小时后台 reaper（D22）
  - References: D22; C9
  - Acceptance: `pytest tests/unit/test_retry.py` 红→绿；连续 3 次 LLM 失败后 `Assessment.status=failed, next_retry_at=now+2h, saved_context_json` 保存；`reap_due()` 查询到期失败项重新评分；循环同策略
  - QA happy: 注入 3 次失败→落库 failed+2h；推进时间后 reaper 成功→done；failure: 一直失败→保持 failed 不丢
  - Commit: `git commit -m "feat: LLM 失败重试与 2 小时后台 reaper"`

### Iter 6 — 邮件发送
- [ ] 14. RED+GREEN：邮件发送服务（smtplib，鼓励模板，自动发送+重试）
  - References: D17,D18; C8
  - Acceptance: `pytest tests/unit/test_email.py` 红→绿；mock smtplib，`send_daily_comments(date)` 给每位 status=done 且未发送的学生发邮件（主题/正文含四段评语与分数）；发送标记避免重复；SMTP 失败重试；同一学生当日多条 Assessment 汇总为一封邮件(D25)
  - QA happy: 2 条 done → 2 封邮件且正文含鼓励开场与改进建议；failure: SMTP 异常→记录未发送，不抛未捕获
  - Commit: `git commit -m "feat: 自动发送鼓励邮件（smtplib）"`

- [ ] 15. RED+GREEN：流水线串联邮件（run_today 末尾触发发信）
  - References: D17,D21; C5,C8
  - Acceptance: `pytest tests/integration/test_run_today_email.py` 红→绿；`run_today()` 评分完成后自动调用 `send_daily_comments`
  - QA happy: mock 全链路 → 评分+发信均发生；failure: 发信失败→评分结果仍保留可重发
  - Commit: `git commit -m "feat: 评测后自动发信串联"`

### Iter 7 — Web UI / API / 调度
- [ ] 16. RED+GREEN：FastAPI 路由与 Jinja2 页面（看板/列表/配置/结果/导出/今日评测）
  - References: D2,D5,D21; C4
  - Acceptance: `pytest tests/integration/test_routes.py` 红→绿；GET `/`(看板含「今日评测」按钮)、`/students`(列表+导入)、`/projects`、`/plans`、`/config`(权重表单)、`/results?date=`、`/export?date=&fmt=xlsx`(下载)、POST `/run-today`
  - QA happy: 上传 fixture xlsx → 列表出现；点「今日评测」→ 结果页出现；failure: 未配 LLM key → `/run-today` 返回明确错误页
  - Commit: `git commit -m "feat: Web UI 路由与 Jinja2 页面"`

- [ ] 17. RED+GREEN：可选登录（ADMIN_PASSWORD）与定时调度（AUTO_RUN_TIME）
  - References: D6,D21; C4,C6
  - Acceptance: `pytest tests/integration/test_auth_schedule.py` 红→绿；设 ADMIN_PASSWORD 时 `/login` 拦截未登录；`AUTO_RUN_TIME` 设置时 APScheduler 每日触发 `run_today`；不设则跳过
  - QA happy: 设密码→未登录访问被拦；failure: 错误密码→401；定时到点→run_today 被调用
  - Commit: `git commit -m "feat: 可选登录与定时调度"`

### Iter 8 — 文档 + AGENTS.md + 全量验证
- [ ] 18. 填充 SPEC.md / PLAN.md / AGENT.md（中文，含各迭代场景与验收）
  - References: D19,D23; C10
  - Acceptance: 三件套覆盖全部 9 迭代的 GWT 场景、接口契约、验收表、Python 命名/分层/禁止项；与最终实现一致
  - QA happy: 文档可被新 agent 读懂并执行；failure: 文档与代码不符→修正
  - Commit: `git commit -m "docs: 完善中文 SPEC/PLAN/AGENT"`

- [ ] 19. 生成仓库 AGENTS.md（中文，给未来 agent 的速查）
  - References: D19; 原始会话目标
  - Acceptance: 根 `AGENTS.md` 含：启动命令(`uvicorn app.main:app --reload`)、安装(`python -m venv .venv && pip install -r requirements.txt`)、`.env` 必填项、导入/导出列约定、一键「今日评测」、LLM/SMTP 配置、测试 `pytest`、架构分层、spec-coding 约定入口
  - QA happy: 新会话读 AGENTS.md 能复现环境；failure: 缺关键命令→补
  - Commit: `git commit -m "docs: 生成中文 AGENTS.md"`

- [ ] 20. 样例数据脚本 + 全量验证
  - References: D7; C6
  - Acceptance: `python -m app.scripts.seed_sample` 生成 `sample_students.xlsx/sample_projects.xlsx/sample_plans.xlsx`；`pytest` 全绿；手动 `uvicorn` 启动后导入样例并点「今日评测」跑通（mock 或真实 token 由教师提供）
  - QA happy: 全测试通过 + 样例导入导出往返成功；failure: 任一测试红→修复后再提交
  - Commit: `git commit -m "chore: 样例数据与全量验证通过"`

## Final verification wave
- [ ] F1. 计划合规审计：每个 todo 均有 References/Acceptance/QA/Commit；无业务假设无证据；任务行语法 `- [ ] N.` / `- [ ] F<number>.` 列零对齐
- [ ] F2. 代码质量评审：分层单向依赖、无吞异常、密钥仅来自 `.env`、测试覆盖导入/评分/重试/邮件关键路径
- [ ] F3. 真实手动 QA：启动 `uvicorn`，导入样例 xlsx，配置（或 mock）LLM/SMTP，点「今日评测」→ 生成 Assessment + 邮件草稿 + 导出 xlsx 一致
- [ ] F4. 范围保真：确认「无教师复核 UI」「全中文文档」「LLM 失败 3 次后落库+2h 重试」均已实现，无范围蔓延

## Commit strategy
- 每迭代全绿后单独提交（Iter 0–8 各 1+ commit），提交信息中文、前缀 `feat:/test:/docs:/build:/chore:`。
- 门禁：上一迭代 `pytest` 全绿方可提交并进入下一迭代（D23 迭代规则）。
- 不在未全绿的迭代提交产品代码；文档/脚手架可在 Iter 0 先行。
- 分支：默认 `main` 直接提交或 `develop` 后合入；由教师本地约定。

## Success criteria
1. 三张表 xlsx（中英文列名）导入成功，学生含邮箱与归一化仓库。
2. 点「今日评测」(或定时) 后，无人工干预即完成：GitHub 同步→AI 四维评分+四段评语→权重算分→落库→自动发鼓励邮件。
3. 导出 xlsx 含每日评分与评语，字段对齐。
4. LLM 连续失败 3 次后该生评估落库(`status=failed`+`next_retry_at=+2h`+上下文)，2 小时后台 reaper 自动重试，不丢数据。
5. `pytest` 全部通过（含 mock 的 GitHub/LLM/SMTP 与失败注入测试）。
6. 仓库含中文 `SPEC.md`/`PLAN.md`/`AGENT.md` 与根 `AGENTS.md`，未来 agent 可据此复现。

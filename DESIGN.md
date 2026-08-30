# 学生 GitHub 日报追踪器 — 前端设计系统（DESIGN.md）

> 本文档为前端设计的唯一事实来源（source of truth），**从当前实现提取**（`app/templates/base.html` 为样式中枢，`app/api/routes.py` 为路由中枢）。
> 原则：**记录什么已存在，而非什么应当存在**。任何新前端工作开始前必须阅读本文档。
>
> **适用范围**：教师本机使用的内网管理工具（FastAPI + Jinja2 + 原生 JS，无构建步骤、无前端框架、无外部 CSS/JS 依赖）。

---

## 1. Atmosphere & Identity（氛围与识别）

**这是一个安静的教学指挥台**：教师每天打开它，看见各小组今日进展、点一下评测、读完一封封鼓励评语。密度适中——数据密集但不拥挤，一切服务于"今天该关注谁"这一个问题。

**签名（signature）**：**Google Material 蓝白体系**。导航栏是一条从 `#1a73e8` 到 `#1558b0` 的渐变丝带，这是全站唯一大色块，也是识别点；内容区是纯白卡片浮在浅灰蓝背景 `#f0f2f5` 上，靠轻阴影而非描边制造层次。状态色借用了 Material 语义（成功绿 / 危险红），任何反馈都一眼可辨。

**气质关键词**：务实、克制、无炫技。动效全部 ≤ 300ms，无装饰动画；交互反馈（按钮位移、卡片浮起、箭头旋转）全部服务于"可点、已点、完成了"的状态信号。

---

## 2. Color（色彩）

### 2.1 核心 Token（`base.html` `:root`）

| Role | Token | 值（Light） | 用途 |
|------|-------|-------------|------|
| 品牌主色 | `--primary` | `#1a73e8` | CTA 按钮、链接、焦点环、进度条端点 |
| 主色暗态 | `--primary-dark` | `#1558b0` | 主按钮 hover、导航渐变末端 |
| 成功 | `--success` | `#34a853` | 评测/完成类按钮、徽标、进度条起点 |
| 成功暗态 | `--success-dark` | `#2d8f47` | 成功按钮 hover |
| 危险 | `--danger` | `#d93025` | 删除按钮、错误提示、失败状态 |
| 危险暗态 | `--danger-dark` | `#b3261e` | 删除按钮 hover |
| 页面底色 | `--bg` | `#f0f2f5` | 内容区背景 |
| 卡片底色 | `--card-bg` | `#ffffff` | 卡片、模态框、表格底 |
| 正文 | `--text` | `#202124` | 标题、正文 |
| 次要文字 | `--text-muted` | `#5f6368` | 标签、提示、说明 |
| 边框 | `--border` | `#e8eaed` | 卡片描边、分隔线、输入框 |
| 阴影基础 | `--shadow` | `0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08)` | 卡片静止态 |
| 阴影悬浮 | `--shadow-hover` | `0 4px 12px rgba(0,0,0,0.15)` | 卡片 hover、模态窗 |
| 圆角 | `--radius` | `12px` | 卡片、模态框、表单卡 |
| 小圆角 | `--radius-sm` | `8px` | 按钮、输入框、徽标底座 |

### 2.2 语义扩展色（实际使用、未入 `:root` 的硬编码）

这些色值在模板中反复出现，**尚未 token 化**——新增代码应优先用下方 Token 化建议：

| 语义 | 值 | 使用位置 | 建议 Token |
|------|-----|---------|-----------|
| 徽标底（蓝） | `#e8f0fe` | `.badge` 背景、`.accent-blue`、`plan-pick` 选中底 | `--badge-bg` |
| 徽标底（绿） | `#e6f4ea` | `.badge-done` 背景 | — |
| 芯片底 | `#f1f3f4` | `.chip`、`.summary-tag`、`.accent-count` 底 | — |
| 渐变晕染色 | `#fafbfd` / `#f8fafc` | `.form-card` 渐变起点、表头底 | — |
| 进度条亮端 | `#81c784` | `.progress-bar` 渐变末端 | — |
| 强调橙 | `#f9ab00` | `.accent-orange`（计划卡片左缘/图标） | — |
| 强调紫 | `#9334e6` | `.accent-purple`（评测记录卡片） | — |
| 平台徽标 GitHub | `#24292f` | 学生表 GitHub 徽标底 | `--badge-github` |
| 平台徽标 Gitee | `#c71d23` | 学生表 Gitee 徽标底 | `--badge-gitee` |
| 无计划红 | `#d93025` | index 卡片「今日计划：无」 | 复用 `--danger` |
| 未评测灰 | `#888` | index 卡片「评测：未评测」 | — |
| 文件拖放区虚线 | `#c1c9d6` | `.file-drop` 边框 | — |
| 计划选择 hover 底 | `#f0f6ff` | `.plan-pick label:hover`（评测页局部） | — |
| 评测块底色 | `#fafbfc` | `.eval-block` 背景（评测页局部） | — |
| 遮罩 | `rgba(0,0,0,0.45)` | `.modal-overlay` | — |

### 2.3 规则

- **主色仅用于交互元素**（按钮、链接、焦点、选中态），不做装饰。
- **成功/危险有严格语义**：成功 = 评测/完成/重开；危险 = 删除/清空/失败。跨语义使用需在 Section 8 记债。
- 所有色值必须能追溯到上表；新语义色先在此表登记再使用。
- 全站**仅一种背景模式（亮色）**，无深色模式，无降级设计。

---

## 3. Typography（排版）

### 3.1 字体栈（`base.html` body）

```
-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
"Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif
```

纯系统字体栈，无外部字体加载（离线可用是硬约束）。中文优先 `PingFang SC` / `Microsoft YaHei`，西文 `-apple-system` / `Segoe UI`。无等宽字体。

### 3.2 字号阶梯（实际使用值）

| 层级 | 值 | 字重 | 用途 |
|------|-----|------|------|
| H1 | `1.75rem` | 700 | 页面主标题（letter-spacing: -0.02em） |
| H1 页头 | `1.5rem` | 700 | `.page-header h1`（index） |
| H2 | `1.25rem` | 600 | 区块标题（下边框 2px 分隔） |
| H3 | `1.1–1.15rem` | 600 | 卡片标题、表单卡标题 |
| 正文 | `16px`（body）/ `0.95rem` | 400 | 默认文本、表格 |
| 次要 | `0.9rem` | 400 | 标签、评语、卡片摘要；muted |
| small | `0.85–0.8rem` | 400–500 | 按钮小号、徽标、图表元信息 |
| 徽标 | `0.75rem` | 500–600 | `.badge` 平台/状态徽标 |

### 3.3 规则

- 全站只用系统字体，**禁止引入外部字体**（离线约束）。
- 正文最小 `0.8rem`（`.chart-meta`），常规正文不低于 `0.9rem`。
- 标题下划线分隔统一用 `--border` 2px。
- H1 兼作页头工具条（`.page-header`）时右侧放按钮组。

---

## 4. Spacing & Layout（间距与布局）

### 4.1 间距体系（实际使用的 rem 阶梯）

项目用 `rem` 做间距（1rem = 16px 基础字号），以 4px 为最小公倍数：

| 值 | 典型用途 |
|-----|---------|
| `0.15rem` ~ 2.4px | `.progress-bar` 圆角细节（可忽略） |
| `0.2rem` / `0.25rem` / `0.3rem` | 徽标内边距、分页按钮内边距 |
| `0.4rem` ≈ 6px | 导航链接内边距、表头背板 |
| `0.5rem` ≈ 8px | 紧凑间距：卡片操作区、标签间隙、表单底部 |
| `0.6rem` µ8px | 表单输入内边距、计划选择项内边距 |
| `0.75rem` = 12px | 导航/卡片内边距、表单控件内边距、模态内边距 |
| `1rem` = 16px | 表单元格水平内边距、文件拖放区、modal-body padding |
| `1.25rem` = 20px | 卡片内边距（标准）、卡片间距 |
| `1.5rem` = 24px | `main` 左右边距、卡片列表间距、`card` margin-bottom |
| `2rem` = 32px | `main` 上下边距、empty 态内边距 |

**关键节奏**：卡片之间的垂直分隔统一 `1.25rem`（`margin-bottom`）；页面容器 `max-width: 1280px` 居中，左右 `1.5rem`。

### 4.2 布局骨架与网格

- **页面骨架**（`base.html`）：sticky 顶栏（渐变丝带，z-index 100）→ 内容区 `main`（1280px 居中、上下 2rem、左右 1.5rem）。
- **项目卡片网格** `.project-grid`：`repeat(auto-fill, minmax(300px, 1fr))`，间距 `1.25rem`。
- **详情汇总网格** `.detail-grid`：`repeat(auto-fill, minmax(320px, 1fr))`，间距 `1.25rem`。
- **表单网格** `.form-grid`：`repeat(auto-fit, minmax(180px, 1fr))`，行距 `0.75rem`、列距 `1rem`；`.span-all` 占满整行。
- **图表网格** `.chart-grid`：`repeat(auto-fill, minmax(300px, 1fr))`，间距 `1rem`。
- **评测双栏** `.eval-grid`（project_eval.html 局部）：`minmax(300px,1fr) minmax(380px,1.4fr)` 非对称双栏 —— 左侧窄栏放"新增计划"、右侧宽栏放"评测目标"。

### 4.3 断点

| 断点 | 行为 |
|------|------|
| `768px`（base.html） | 导航收紧、`main` 内边距 `1rem`、project-grid / detail-grid 变单列 |
| `820px`（project_eval.html 局部） | `.eval-grid` 变单列 |

---

## 5. Components（组件）

以下皆为**当前实现中复用 ≥2 次**的组件；每个均给出结构、变体、状态、可达性现状与动效。

### 5.1 顶栏导航（`base.html`）

- **结构**：`<nav>` 内三个链接 — `.brand`（"GitHub 日报追踪器"，加粗 + 下划线式底边）+ 「看板」+「配置」。
- **样式**：渐变底 `linear-gradient(135deg, var(--primary), #1558b0)`；链接默认 `rgba(255,255,255,0.9)`。
- **状态**：hover → 白色 + `rgba(255,255,255,0.15)` 圆角底色；无 active/当前页高亮（**已知缺口**）。
- **布局**：flex，`gap: 1.5rem`，sticky 吸顶。

### 5.2 卡片 `.card`（全站布局原件）

- **结构**：圆角白卡 + 1px `--border` 描边 + `--shadow`。
- **变体**：
  - 静态 `.card`（项目卡、列表容器、图表容器）
  - `details.card`（评测记录、配置页折叠卡）— summary 前有 `▸` 箭头，展开转 90°；可 `<details open>` 默认展开首项；内容区需包 `.card-body`（顶部 `0.75rem` 内边距）
  - `.form-card`（渐变底 `#fafbfd→#fff` 的表单承载卡，标题区 `.fc-icon` 浅蓝圆角图标格 + H3）
  - `.summary-card`（可点击汇总卡，见 5.7）
- **状态**：hover → `--shadow-hover`（0.2s ease）。
- **空态**：内部放 `.empty`（虚线框、斜体灰字居中）。

### 5.3 按钮 `.btn`

- **结构**：inline-flex 居中，`0.5rem 1rem` 内边距，`--radius-sm` 圆角，无边框。
- **变体**：
  | 变体 | 底色 | 用途 |
  |------|------|------|
  | `.btn`（默认） | 透明 / 白 | 次要操作（编辑、返回、取消） |
  | `.btn-primary` | `--primary` | 主操作（创建、保存、评测、导入） |
  | `.btn-success` | `--success` | 肯定操作（完成、重开、开始评测、导出） |
  | `.btn-danger` | `--danger` | 破坏操作（删除、清空） |
  | `.btn-small` | 叠加任意变体 | 紧凑操作（行内按钮、卡片操作区） |
- **状态**：hover → 上浮 1px + 变暗（primary/success/danger 各用暗态色）；active → `translateY(0)`；均 0.15s ease。
- **可达性**：无 `:focus-visible` 自定义样式（**已知缺口**）。破坏操作由 `onsubmit="return confirm(...)"` 承担误点防线。

### 5.4 徽标 `.badge` / `.chip`

- **`.badge`**：小圆角胶囊（12px 圆角），`#e8f0fe` 底 + primary 字（尺寸约 0.75rem）。用途：进度百分比、平台（GitHub `#24292f` 白字 / Gitee `#c71d23` 白字，行内覆盖）、「已完成」。
- **`.badge-done`**：`#e6f4ea` 底 + success 字（完成态）。
- **`.chip`**：灰底 `#f1f3f4` + 1px 边框胶囊。用途：学生姓名标签、计划摘要标签（`.summary-tag` 同构）。

### 5.5 表格（全站标准化）

- **结构**：`border-collapse: separate; border-spacing: 0`；`th` 灰底 `#f8fafc` + 大写小字（text-transform + letter-spacing 0.05em）；`td` 下边框 1px `--border`。
- **列布局**：`th/td` 内边距 `0.875rem 1rem`。
- **状态**：行 hover → `#f8fafc` 底。
- **特化单元格**：`.comment-cell`（评语，max-width 400px、`white-space: pre-wrap` 保留换行）。
- **失败行**：`style="opacity:0.6"`（project_assessments）。
- **行内编辑行 `.edit-row`**：隐藏行（`display:none`）内嵌 `.form-card` 编辑表单，`toggleEdit(id)` 切换显隐（project_students）。

### 5.6 表单

- **输入控件**（input/select/textarea）：`0.6rem 0.75rem` 内边距、`--radius-sm`、1px `--border`；**focus → primary 边框 + 3px `rgba(26,115,232,0.1)` 光环 + outline:none**（0.15s ease）。
- **`.form-group`**：标签在上（muted 小字）+ 控件在下；`.form-group label` 块级、底部 0.4rem。
- **`.inline-form`**：flex 换行、`gap: 0.75rem`、`align-items: flex-end`，子项 `flex:1; min-width:150px`（评测页工具条用）。
- **`.form-actions`**：表单底部操作区 — flex 左对齐 `gap: 0.75rem`、换行（保存/取消按钮组），底部 `0.85rem` 边距。
- **`.file-drop`**：虚线框（`#c1c9d6`）+ hover 变 primary 边框 + `#f7faff` 底；内含 `.fd-label`（📄 标签 + 文件选择说明）与 `input[type=file]`。
- **表格行编辑**：见 5.5 `.edit-row`（行内展开编辑表单）。

### 5.7 项目卡元信息

- **`.status-line`**（index 项目卡）：日期/今日计划数/评测完成数的元信息行 — flex 左对齐、`gap: 0.5rem`、muted 色；「无计划」内联红 `#d93025`、「未评测」内联灰 `#888`。
- **`.project-card-head`**：卡片头部 flex 两端对齐 — 左侧标题链接 `.project-link`（primary 加粗），右侧进度徽标（右上角不必左侧）。
- **`.card-actions`**：卡片底部操作区 — 上边框 `--border` 分隔，flex 换行 `gap: 0.5rem`（评测/编辑/完成/删除按钮组）。
- **`.eval-btn`**（index 项目卡）：`btn-small btn-success` 之上的评测触发按钮，JS `data-project`/`data-name` 属性携带上下文，点击打开评测配置模态框。

### 5.8 可点击汇总卡 `.summary-card`（project_detail 页导航核心）

- **结构**：卡片内四段 — 左缘色条（`::before` 4px 宽、按 accent 上色）+ `.card-accent`（`.accent-icon` emoji 图标 + 标题 + `.accent-count` 计数胶囊）+ `.card-summary`（摘要标签 `.summary-tags`/`.summary-tag`）+ `.card-action`（右下"管理 →"）。
- **变体**（按左侧条颜色）：`.accent-blue` 学生 / `.accent-orange` 计划 / `.accent-green` 分数趋势 / `.accent-purple` 评测记录。
- **状态**：hover → `translateY(-2px)` + `--shadow-hover`（0.2s ease）；整卡是 `<a>`，cursor pointer。
- **布局**：横向 `auto-fill minmax(320px, 1fr)` 网格（`.detail-grid`）。

### 5.9 模态框 `.modal`（index 页两处：新建项目、评测配置）

- **结构**：`.modal-overlay`（fixed 全屏遮罩 `rgba(0,0,0,0.45)` 居中，`overflow-y:auto`）→ `.modal`（白卡、`--shadow-hover`、max-width 460px、`max-height: calc(100vh - 2rem)` 纵向 flex）→ `.modal-header`（标题 + `.modal-close` ✕）/ `.modal-body`（表单 labels）/ `.modal-footer`（取消 + 确认）。
- **变体**：`.modal-wide` 720px / `.modal-full` 960px（已定义，当前页面未使用）。
- **行为**：JS 控制 `hidden` 属性显隐；点遮罩、点 ✕、Esc 均可关闭；表单提交后走 303 重定向刷新。
- **可达性**：无 role="dialog"/aria-modal/焦点圈定（**已知缺口**，见 Section 8）。

### 5.10 进度指示 `.progress-wrap` / `.progress-bar`

- **结构**：8px 高圆角轨道（`--border` 底）+ 渐变填充（success → `#81c784`，`width` 由 JS 内联设置）。
- **用途三处**：项目卡进度百分比（index）、项目详情总进度（max-width 480px）、评测实时进度（eval 页/卡片，配 `.progress-label`/`.eval-progress-text` 文案）。
- **动效**：`width 0.3s ease`。

### 5.11 空态 `.empty`

虚线边框（2px dashed `--border`）+ 灰斜体居中文案，内边距 `2rem`。所有列表/结果页的兜底。

### 5.12 SVG 图表（分数趋势，零依赖内联）

- **来源**：`app/utils/` 的 SVG builder（`test_svg_chart.py` 覆盖）。
- **呈现**：project_charts.html 中 `{{ chart | safe }}` 直接内联；`.chart-item` 灰边框卡内渲染，配 `.chart-meta`（"已评 N 天"）。
- **两块**：每日平均分折线（单张大卡）+ 每学生分数变化（chart-grid 网格多卡）。

### 5.13 行内编辑行（project_students）

- **结构**：每条学生行后紧跟 `<tr id="edit-{id}" class="edit-row" style="display:none">` 内嵌 `.form-card` 编辑表单（姓名/邮箱/仓库）。
- **行为**：`toggleEdit(id)` JS 切换该行 display；保存走 `/students/{id}/update`（303 回跳）。

### 5.14 评测面板局部组件（仅 project_eval.html）

这些组件只在该页使用（页面级 `<style>` 块定义，未进 base.html）：

- **`.eval-grid`**：非对称双栏布局（`minmax(300px,1fr) minmax(380px,1.4fr)`），820px 以下单列。
- **`.eval-block`**：浅灰底 `#fafbfc` 信息块（`.card` 同级），用于放置「新增计划」「选择评测目标」。
- **`.step-num`**：圆形步骤号（白字 primary 底 1.6rem 圆），表示评测步骤 1/2。
- **`.quick-add`/`.quick-go`**：紧凑两栏表单与操作行（添加计划按钮 + 管理入口）。
- **`.plan-pick`**：可滚动的计划单选列表（max-height 300px）— 每项 `.plan-meta`（日期加粗 primary + 内容 + `small` 对象）+ `.plan-date`；hover primary 边框浅蓝底，`:has(input:checked)` 选中项 `#e8f0fe` 底；radio 用 `accent-color: var(--primary)`；无计划时 `.plan-none` 灰斜体占位。
- **`.progress-zone`**：虚线框（`hidden` 默认隐藏）内进度条 + `.progress-label` 文案；评测异步轮询状态实时填充。

---

## 6. Motion & Interaction（动效与交互）

### 6.1 时序表

| 类型 | 时长 | 缓动 | 元素 |
|------|------|------|------|
| 微交互 | 0.15s | ease | 按钮色变/位移、导航 hover、输入 focus、分页 hover、badge 悬浮 |
| 卡片悬浮 | 0.2s | ease | `.card` 阴影、`.summary-card`/`.btn` 的 `translateY` |
| 进度填充 | 0.3s | ease | `.progress-bar` width |
| details 箭头 | 0.15s | ease | summary `::before` 旋转 90° |

### 6.2 规则

- **只用 `transform` / `opacity` / `box-shadow` / `width` 做动画**，无布局属性动画（符合高性能原则）。
- **动效服务于状态**：按钮 hover 亮暗 = 可点；卡片浮起 = 可进；进度条 = 正在发生。无装饰性/无意义动画。
- **评测轮询**：`eval-start` 后 fetch 提交 → 拿 `job_id` → `setInterval` 每 2–3s 拉 `/eval-progress/{job_id}` → 完成后重定向 `/assessments` 或 `location.reload()`；409（任务冲突）内联提示且不破坏页面。
- **无 scroll 驱动动画、无 IntersectionObserver 需求**（页面均为短滚动或列表页）。

---

## 7. Depth & Surface（深度与表面）

- **策略：混合式（shadow 主导 + 少量描边/渐变）**：
  | 层级 | 手段 | 元素 |
  |------|------|------|
  | L0 页面底 | `#f0f2f5` 纯色 | body |
  | L1 静止卡 | 1px `--border` + `--shadow`（双层轻影） | `.card`、表格容器 |
  | L2 悬浮卡 | `--shadow-hover` | hover 态、`.form-card` 上加渐变（`#fafbfd→#fff`） |
  | L3 模态 | `--shadow-hover` + 45% 黑遮罩 | `.modal` |
  | 唯一大色面 | 渐变丝带 | 顶栏（识别点） |
- 无玻璃拟态、无毛玻璃、无大面积渐变；渐变只出现于顶栏 + 进度条。

---

## 8. Accessibility Constraints & Accepted Debt（可达性约束与已接受债务）

### 8.1 目标与现状

- **对标 WCAG 2.1 AA**：正文/背景对比（`#202124` on `#fff` ≈ 15:1 ✅、`#5f6368` on `#fff` ≈ 4.6:1 ✅）、按钮白字 on primary/success/danger ✅。
- **键盘**：全部表单可用 Tab 到达，提交可用 Enter ✅；JS 交互（模态、评测启动、行内编辑）均挂真实 button/链接 ✅。
- **动画**：无自动播放/闪烁内容 ✅；动效全部瞬时（≤0.3s）无需 `prefers-reduced-motion` 豁免（无长动画）。

### 8.2 已接受债务（Accepted Debt）

| 债务项 | 位置 | 为何接受 | 退出条件 |
|--------|------|----------|----------|
| 无 `:focus-visible` 样式 | 全局按钮/链接 | focus 用输入框光环替代，全站统一；改动涉及所有按钮类 | 接入 `:focus-visible` 统一样式时 |
| 模态框无 ARIA（role="dialog"/aria-modal/焦点圈定/Esc 可关但无还原焦点） | index.html 两个模态 | 内网教师单用户工具，键盘用户面窄 | 添加 role/aria 且测试不回归 |
| 导航无当前页/激活态高亮 | base.html nav | 页面少（看板/配置），依赖浏览器自身视觉 | 页面数 >5 时补 active 态 |
| **emoji 充当图标**（📅📋✅👥📈📥👤✏️💾🗑➕▶⚠️❌📊📄） | 全部模板 | 零依赖零构建约束下最轻方案；当前视觉风格已统一 | 引入 SVG sprite / icon font 时全量替换 |
| 未 token 化的散落色值 | 见 2.2 表 | 已在本文档登记，可安全重构 | 出现第 N+1 次新增用途时顺手 token 化 |
| 无深色模式 | 全局 | 内网日间工具，需求未提 | — |
| `.btn` hover 依赖 `translateY` 位移提示可点 | 全局 | 已配色变双重信号 | 无障碍审查要求时补充 |

### 8.3 硬约束

- **零外部依赖**：不可引入 CDN / 网络字体 / 框架（内网离线可用是产品前提）。
- **中文优先**：所有文案中文，`lang="zh-CN"`。
- **每文件 ≤ 1 个内联 `<style>` 块 + 尾部 `<script>`**，遵循现有模板组织。

---

## 附录 A — 页面与路由映射（当前实现事实）

| 路由（方法） | 渲染页面 | 页面角色 |
|-------------|---------|---------|
| `GET /` | `index.html` | 看板：项目卡网格（进行中）+ 表格（已完成）+ 新建/评测模态框 |
| `GET /students` | `students.html` | 全量学生列表 + 导入 + 清空 |
| `POST /students`、`/students/import` | 303 重定向 | 学生导入 |
| `POST /students/add` | 303 | 添加学生 |
| `POST /students/{id}/update` | 303 | 编辑学生 |
| `POST /students/{id}/delete` | 303 | 删除学生 |
| `POST /students/clear`、`/projects/{id}/students/clear` | 303 | 清空（全局/项目级） |
| `GET /projects/{id}` | `project_detail.html` | 详情：总进度 + 4 张汇总导航卡 |
| `GET /projects/{id}/students` | `project_students.html` | 项目学生管理：导入/添加/行内编辑/清空 |
| `GET /projects/{id}/plans` | `project_plans.html` | 项目计划管理 |
| `GET /projects/{id}/plans`（Accept: JSON） | JSON | 评测模态框加载计划 |
| `GET /projects/{id}/charts` | `project_charts.html` | SVG 分数趋势 |
| `GET /projects/{id}/assessments` | `project_assessments.html` | 按日折叠的评测记录 + 删除 |
| `POST /projects/{id}/assessments/delete`、`/assessments/{aid}/delete` | 303 | 删除整日/单条记录 |
| `GET /projects/{id}/edit` / `POST` | `project_edit.html` | 编辑项目 |
| `POST /projects/{id}/complete` / `reopen` / `delete` | 303 | 项目状态/删除 |
| `GET /projects/{id}/eval` | `project_eval.html` | 评测面板：新增计划 + 计划选择 + 模式/范围/抽样 + 实时进度 |
| `POST /projects/{id}/run-eval` | JSON `{job_id}`；409 冲突 | 启动评测（并发锁） |
| `GET /eval-progress/{job_id}` | JSON 进度 | 轮询 |
| `GET /plans` | `plans.html` | 全量计划 + 新增 |
| `GET /plans/{id}/edit` / `POST` | `plan_edit.html` | 编辑计划 |
| `POST /plans`、`/plans/{id}/delete` | 303 | 新增/删除计划 |
| `GET /config` | `config.html` | 权重 / LLM / SMTP 三折叠配置卡 |
| `POST /config`、`/config/llm`、`/config/smtp` | 303 | 权重 / LLM / SMTP 保存 |
| `GET /results?date=` | `results.html` | 按日查询评测结果 + 导出按钮 |
| `GET /export?date=&fmt=xlsx` | 文件下载 | 导出 |
| `POST /run-today` | 303 → `/results?date=` | 一键今日评测（全项目） |

## 附录 B — 模板继承关系

```
base.html（布局 + 全局样式 + 导航）
├── index.html            看板
├── students.html         全量学生
├── project_detail.html   项目详情
├── project_students.html 项目学生
├── project_plans.html    项目计划
├── project_charts.html   分数趋势
├── project_assessments.html 评测记录
├── project_eval.html     评测面板（页面级局部样式 + 轮询 JS）
├── project_edit.html     项目编辑
├── plans.html            全量计划
├── plan_edit.html        计划编辑
├── config.html           配置（三折叠）
└── results.html          结果查询
```

> **不一致标注**（提取时发现）：`students.html`（全量学生页）与 `project_students.html`（项目学生页）两者结构平行但表格列不同（前者含学号/所属项目列且无行内编辑，后者含编辑/删除操作列）；`plans.html` 的表格列直接把 `project_id`/`student_id` 数字原样展示而非名称——这两处建议在下次功能迭代时按 `.form-card`/行内编辑模式统一，未获批准前不改动。
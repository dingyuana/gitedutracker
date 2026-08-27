# Issues — student-github-tracker

Problems and gotchas encountered during work on this plan.

_Auto-scaffolded by /start-work. Append new entries below - never overwrite._

---

## 2026-08-27 修复 gitee/github 平台区分问题
- 根因: import_service 先 normalize 成 owner/repo → 模型 validator 看不到 http 前缀 → github_url 丢失
- pipeline/github_snapshot 使用 github_repo (owner/repo) → detect_platform 默认 github
- 模板只显示 github_repo (无平台信息)
- 修复: import_service 保留完整 URL; pipeline 用 github_url or github_repo; 模板显示完整 URL+平台徽标
- 朱律锦镜像已删除重建 (gitee origin ✓)
- 陆勃瑀地址仍待确认 (github/gitee 均 404)

# Learnings — student-github-tracker

Conventions, patterns, and successful approaches discovered during work on this plan.

_Auto-scaffolded by /start-work. Append new entries below - never overwrite._

---

## 2026-08-27 gitee/github 平台识别教训
- mirror_service.detect_platform 只在 repo 字符串含 "gitee.com" 时返回 gitee
- 传 owner/repo 格式 → 默认 github → gitee 仓库被错误克隆到 github mirror
- 修复: 传递完整 URL (github_url or github_repo) 确保 detect_platform 能识别
- import_service 必须在 model_validate 前保留原始 URL，或在 student_data 中显式设置 github_url

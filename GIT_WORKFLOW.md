# GIT_WORKFLOW.md — 提交 / 分支 / CI 规范

## 分支
- 主开发在 `main`。每功能直接提交 `main`（单人项目，简化流程）。
- 进化循环中若改动较大或高风险，可建 `evol/<slug>` 分支，测试绿后合并 `main` 并删分支。

## 提交
- 约定式提交：`feat: <功能>` / `fix: <修复>` / `test: <测试>` / `refactor: <重构>` / `docs: <文档>` / `chore: <杂项>` / `ci: <CI>`。
- 一功能一提交，粒度小且自包含（含该功能测试）。
- 提交信息体简述"做了什么 + 为什么"（可选 body）。
- **永不提交**：`.env`、`*.db`、`__pycache__/`、`.venv/`、`data/failed_digests/`、密钥。

## .gitignore 必含
```
.env
.venv/
__pycache__/
*.pyc
data/*.db
data/*.db-journal
data/failed_digests/
.pytest_cache/
.coverage
htmlcov/
```

## GitHub
- 仓库创建：`gh repo create info-digest --public --source=. --remote=origin --push`（若 `gh` 不可用，本地提交并在 STATUS 标注"待配置 remote"，不阻塞后续开发）。
- Secrets（用户在仓库 Settings→Secrets 配置；CI 文档说明）：
  - `FEISHU_WEBHOOK`、`FEISHU_SECRET`
  - `DINGTALK_WEBHOOK`、`DINGTALK_SECRET`
- CI 必须绿才算该功能交付完成；CI 红 → 进入自愈。

## CI 工作流
- `ci.yml`：on push/PR；`pip install -r requirements.txt`；`pytest --cov=infodigest --cov-fail-under=<阈值>`；`ruff check`。
  - 覆盖率门禁起始 60%，每完成一个 Phase 上调 5pt，目标 ≥ 85%。
- `digest.yml`：on schedule(cron `0 1,9 * * *`) + workflow_dispatch；`python -m infodigest.cli run`；注入 secrets。
- `release.yml`：on tag `v*`；生成 changelog 并建 GitHub Release。

## 推送失败处理
- `git push` 失败（无 remote/网络）→ 记录 STATUS，继续本地提交，不阻塞。下一轮重试 push。

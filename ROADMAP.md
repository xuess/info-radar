# ROADMAP.md — 功能交付路线 (每项 = 一次提交)

> 顺序即交付顺序。每项完成即 `git commit`。每项必须带测试。完成全部后进入 EVOLUTION LOOP。

## Phase 0 — INIT (脚手架)
- [ ] R0.1 git 仓库初始化 + `.gitignore` + `README.md` 骨架
- [ ] R0.2 `pyproject.toml` + `requirements.txt` (锁定: feedparser, httpx, beautifulsoup4, lxml, jinja2, pyyaml, pytest, pytest-cov)
- [ ] R0.3 `infodigest/config.py` dataclass + yaml 加载 + `config/settings.yaml`
- [ ] R0.4 `config/feeds.yaml` 源注册表 (SOURCES_SEED 前 8 源)
- [ ] R0.5 `config/rater.yaml` 评分配置
- [ ] R0.6 `.github/workflows/ci.yml` 骨架 (install + pytest)
- [ ] R0.7 `STATUS.md` + `BACKLOG.md` 初始化
- [ ] R0.8 首次提交 `chore: init project scaffold`

## Phase 1 — 采集层
- [ ] R1.1 `collector/fetcher.py`: httpx 抓取, 超时/重试/UA, ETag/Last-Modified 增量 + test
- [ ] R1.2 `collector/parser.py`: feedparser 解析 RSS2/Atom/RDF → Entry + test (用本地 fixture)
- [ ] R1.3 `collector/normalizer.py`: HTML→纯文本, 标题归一化, 时间解析 + test
- [ ] R1.4 `collector/dedup.py`: sha1 主键 + 标题 Jaccard 二次去重 + test
- [ ] R1.5 `tests/fixtures/*.xml` 样本 (rss2/atom/bad)

## Phase 2 — 评级层
- [ ] R2.1 `rater/scorer.py`: 五维评分 + 分级 + test (按 RATING_SPEC)
- [ ] R2.2 离线评分回归 fixture + test (给定 Entry 断言分数区间)

## Phase 3 — 存储层
- [ ] R3.1 `storage/models.py` 建表 + 迁移 + test
- [ ] R3.2 `storage/repo.py`: upsert/recent_titles/pending_digest + test (临时 db)

## Phase 4 — 排版层 (无 LLM)
- [ ] R4.1 `formatter/builder.py`: Jinja2 渲染 + test
- [ ] R4.2 `config/templates/feishu_card.j2` + `dingtalk_md.j2` + `digest_section.j2`
- [ ] R4.3 分段构建 (条目数/字节数上限) + test

## Phase 5 — 推送层
- [ ] R5.1 `delivery/base.py` Channel 抽象 + test
- [ ] R5.2 `delivery/feishu.py` interactive card + test (mock server 用本地 httpx mock)
- [ ] R5.3 `delivery/dingtalk.py` markdown + HMAC 签名 + test
- [ ] R5.4 `delivery/limiter.py` 令牌桶 + test
- [ ] R5.5 失败落盘 `data/failed_digests/` + 重试 + test

## Phase 6 — 编排层
- [ ] R6.1 `scheduler/runner.py`: collect→rate→store→deliver 编排 + RunReport + test
- [ ] R6.2 `cli.py`: `collect`/`rate`/`deliver`/`run` 子命令 + test
- [ ] R6.3 `scripts/opml_import.py`: OPML → feeds.yaml + test

## Phase 7 — CI/CD
- [ ] R7.1 `.github/workflows/digest.yml`: cron 调度 + secrets 注入
- [ ] R7.2 `.github/workflows/release.yml`: tag → changelog
- [ ] R7.3 覆盖率门禁脚本 (pyproject cov fail-under)

## Phase 8 — 文档与验收
- [ ] R8.1 `docs/REQUIREMENTS.md` (需求分析师)
- [ ] R8.2 `docs/DESIGN.md` + ADR (技术负责人)
- [ ] R8.3 `docs/DATA_MODEL.md` (架构师)
- [ ] R8.4 `docs/UAT.md` 端到端剧本 + 实跑证据 (UAT)
- [ ] R8.5 `docs/CONTRIBUTING.md` + 源贡献流程
- [ ] R8.6 `README.md` 完整 (徽章/快速开始/配置/部署/截图占位)

## Phase 9 — 进化循环入口
ROADMAP 全绿后，进入 `SELF_EVOLUTION.md` 的循环，永不提前结束。

# DESIGN.md — 技术设计记录

> 技术负责人产出。关键决策（ADR）、依赖选型、风险与缓解。

## ADR-001: 全链路确定性，禁用 LLM

- **状态**：Accepted
- **背景**：信息聚合系统若依赖 LLM 做摘要/评级，引入成本、延迟、不可复现性与供应商锁定。
- **决策**：采集、解析、去重、评级、排版、推送全链路用确定性代码（feedparser / 规则评分 / Jinja2 / webhook）。
- **结果**：可复现、可测试、零 API 成本、CI 可跑。关键词命中用配置字典，非 LLM 推理。

## ADR-002: SQLite 作为唯一存储

- **状态**：Accepted
- **背景**：需持久化条目/运行记录/源缓存，但部署在 GitHub Actions 无常驻服务。
- **决策**：SQLite 单文件库（WAL 模式），随仓库运行时 `data/` 目录（gitignore）。
- **替代方案**：Postgres（需服务，违反零运维）、纯 JSON 文件（无索引/查询弱）。
- **结果**：零运维、单文件、标准 SQL、支持增量查询。CI 每次运行新建/复用本地 db。

## ADR-003: GitHub Actions 作为调度器

- **状态**：Accepted
- **背景**：需每日定时运行，但不想维护常驻服务/cron。
- **决策**：`.github/workflows/digest.yml` cron `0 1,9 * * *`（UTC 01/09 = 北京 09/17），secrets 注入 webhook。
- **结果**：零运维、免费额度、版本随仓库走。本地可选 APScheduler 自托管。

## ADR-004: httpx + feedparser 组合

- **状态**：Accepted
- **决策**：httpx（同步 Client，follow_redirects，ETag/Last-Modified 增量头）+ feedparser（RSS2/Atom/RDF 兼容解析）。
- **理由**：httpx 比 requests 更现代、支持 HTTP/2（虽未启用）、API 一致；feedparser 是 RSS 解析事实标准，容错好（坏 feed 返回空而非崩溃）。

## ADR-005: Jinja2 模板纯构建推送内容

- **状态**：Accepted
- **决策**：飞书 interactive card JSON 与钉钉 markdown 均由 Jinja2 模板渲染，不调 LLM。
- **细节**：模板含 grade emoji、分段渲染（segment_entries 按 max_entries/max_bytes）。

## ADR-006: 令牌桶限流

- **状态**：Accepted
- **决策**：线程安全令牌桶（TokenBucket），飞书 5/min、钉钉 20/min，acquire 阻塞至有令牌或超时。

## ADR-007: 失败落盘 + 下次重试

- **状态**：Accepted
- **决策**：webhook 重试 3 次失败后，消息写 `data/failed_digests/<ts>_<channel>_<batch>.json`，下次运行 load 重发。

## 依赖选型

| 依赖 | 版本 | 用途 | 必要性 |
|---|---|---|---|
| feedparser | 6.0.11 | RSS/Atom/RDF 解析 | 核心 |
| httpx | 0.27.2 | HTTP 抓取 | 核心 |
| beautifulsoup4 | 4.12.3 | HTML 清洗 | 核心 |
| lxml | 5.2.2 | bs4 解析后端 | 核心 |
| Jinja2 | 3.1.4 | 模板渲染 | 核心 |
| PyYAML | 6.0.1 | 配置加载 | 核心 |
| APScheduler | 3.10.4 | 本地可选调度 | 可选 |
| pytest | 8.2.2 | 测试 | dev |
| pytest-cov | 5.0.0 | 覆盖率 | dev |

- 无 LLM SDK（openai/anthropic 等）。
- 无 ORM（SQLAlchemy）——SQLite 直接用 sqlite3 标准库，避免过度抽象。
- 无 Web 框架——CLI + Actions。

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| RSS 源失效/改版 | 坏源自动 disable，status 记录；进化循环定期验证 |
| GitHub Actions 定时不精确 | cron 为主，workflow_dispatch 可手动触发 |
| webhook 限流/封禁 | 令牌桶限流 + 指数退避 |
| SQLite 并发（CI 多 job） | 单 job 串行；WAL 模式 |
| 评分阈值需调参 | rater.yaml 可配；离线回归 fixture 防回归 |
| 密钥泄露 | .gitignore + Secrets；ruff/CI 不含密钥检查（不入仓即安全）|

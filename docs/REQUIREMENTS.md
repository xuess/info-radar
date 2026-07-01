# 需求规格说明书 — InfoDigest

> 需求分析师产出。覆盖用户故事、功能清单（MoSCoW）、非功能需求、验收标准（Given-When-Then）。

## 1. 项目概述

InfoDigest 是一个轻量、零运维、可自托管的 RSS 信息聚合器。定时从配置的 RSS 源采集信息，经去重、规则评级、模板排版后，推送到飞书/钉钉群机器人。全链路确定性代码，**不依赖任何大模型**。通过 GitHub Actions 部署与调度。

## 2. 用户故事

- **US-1（信息消费者）**：作为技术从业者，我希望每天早晚在飞书/钉钉群收到一份精选信息摘要，包含 AI/安全/开源等领域的高价值条目，省去逐个浏览 RSS 的时间。
- **US-2（群管理员）**：作为群管理员，我希望配置一个自定义机器人 webhook，即可开始接收推送，无需部署服务器。
- **US-3（源贡献者）**：作为社区贡献者，我希望通过 PR 向 `feeds.yaml` 添加新的 RSS 源，经维护者审核后纳入推送。
- **US-4（自托管用户）**：作为自托管用户，我希望克隆仓库、配置 webhook 环境变量、即可本地或 CI 定时运行。
- **US-5（调参用户）**：作为高级用户，我希望通过修改 `rater.yaml` 调整关键词权重与评分阈值，定制推送内容。

## 3. 功能清单（MoSCoW）

### Must Have
- F1: RSS 源采集（HTTP fetch + feedparser 解析 RSS2/Atom/RDF）
- F2: 增量抓取（ETag/Last-Modified，304 跳过）
- F3: HTML 清洗 + 标题归一化 + 时间解析（UTC）
- F4: 去重（sha1 主键 + Jaccard 标题相似度二次去重）
- F5: 五维规则评分（权威/新鲜度/关键词/唯一性/热度）+ A/B/C 分级
- F6: SQLite 持久化（entries/digests/runs/sources）
- F7: Jinja2 模板排版（飞书 interactive card / 钉钉 markdown）
- F8: 分段发送（条目数/字节数上限）
- F9: 飞书 webhook 推送（含签名）
- F10: 钉钉 webhook 推送（含 HMAC 签名）
- F11: 限流（飞书 5/min、钉钉 20/min 令牌桶）
- F12: 失败落盘重试（`data/failed_digests/`）
- F13: GitHub Actions cron 调度 + secrets 注入
- F14: CLI（run/collect/report/sources）

### Should Have
- F15: OPML 批量导入
- F16: 坏源自动降级/禁用
- F17: 运行报告（runs 表统计）
- F18: 覆盖率门禁（≥85%）

### Could Have
- F19: 多模板（每日精选/每周回顾/分类摘要）
- F20: 跨源去重（同新闻多源只推 authority 最高者）
- F21: 源健康度指标 + 自动降权
- F22: 飞书 card 分区高亮 A 级

### Won't Have（本阶段）
- F23: 任何大模型调用（铁律禁止）
- F24: Web UI / 管理后台
- F25: 全文检索

## 4. 非功能需求

- **NFR-1 性能**：单次运行采集 ≤20 源在 60s 内完成（含重试）；SQLite 单库。
- **NFR-2 可用性**：webhook 失败不崩溃，落盘待发；坏源不阻塞其他源。
- **NFR-3 安全**：密钥/Token 只走环境变量/GitHub Secrets，永不入仓库；`.env` 在 `.gitignore`。
- **NFR-4 可观测**：每次运行写 `runs` 表；CLI `report` 输出统计。
- **NFR-5 无 LLM**：采集/解析/去重/评级/排版/推送全链路确定性代码。
- **NFR-6 可配置**：源、权重、关键词、阈值、推送通道均可经 `config/*.yaml` 调整，禁止硬编码。
- **NFR-7 可测试**：不依赖网络的本地 fixture 测试；覆盖率 ≥85%。

## 5. 验收标准（Given-When-Then）

### AC-F1 采集
- Given 一个有效 RSS2 feed URL
- When 执行 `cli collect`
- Then 条目被解析并入库，`entries` 表新增行，源记录含 etag/last_modified

### AC-F5 评级
- Given 一条 1 小时内发布、标题命中关键词、高权威源的条目
- When 评分
- Then raw_score ≥ 75，grade = "A"
- Given 一条 8 天前发布的条目
- Then freshness = 0，grade = "C"

### AC-F9/F10 推送
- Given 配置了 FEISHU_WEBHOOK 和 FEISHU_SECRET 环境变量
- When 有 grade ≥ B 的待推送条目
- Then 飞书收到一条 interactive card 消息，含 timestamp+sign 签名
- Given 钉钉 webhook + secret
- Then 钉钉收到 markdown 消息，URL 含 timestamp+sign 查询参数

### AC-F12 失败重试
- Given webhook 返回 5xx 或超时
- When 重试 3 次仍失败
- Then 失败消息写入 `data/failed_digests/<id>.json`，下次运行可重试

### AC-F13 CI 调度
- Given GitHub Actions cron `0 1,9 * * *`
- When 触发
- Then 执行 `python -m infodigest.cli run`，secrets 注入，推送结果

### AC-NFR-5 无 LLM
- Given 全量代码 `grep -ri "openai\|llm\|gpt\|anthropic\|chatgpt"`
- Then 无任何大模型 API 调用代码（仅关键词命中评分中的字符串 "llm"/"gpt" 作为评分词，非 API 调用）

## 6. 自检

- [x] 每条需求可测
- [x] 无 LLM 依赖
- [x] 覆盖飞书+钉钉双通道
- [x] 覆盖可配置源与关键词

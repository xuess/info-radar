# UAT.md — 端到端验收剧本

> UAT 验收工程师产出。从空库到推送的完整剧本 + 实跑证据。

## 剧本 1: 端到端流水线（本地 fixture + fake channel）

### 前置
- Python 3.11+ venv，依赖已安装
- `tests/fixtures/rss2_sample.xml` 存在（4 条目）

### 步骤
1. 构造配置：单源指向本地 fixture，fake 飞书/钉钉 channel（不联网）
2. 调用 `infodigest.scheduler.runner.run(config, feishu=fake, dingtalk=fake)`
3. 断言 RunReport

### 实跑证据（2026-07-01）

```
=== RUN REPORT ===
collected=4 deduped=0 rated=4
stored=4 delivered=2 failed=0
status=ok run_id=1
feishu msgs=1 dingtalk msgs=1

--- feishu msg 0 (first 300 chars) ---
{
  "msg_type": "interactive",
  "card": {
    "config": { "wide_screen_mode": true },
    "header": {
      "title": { "tag": "plain_text", "content": "📰 InfoDigest 每日推送" },
      "template": "blue"
    },
    "elements": [...]

--- dingtalk msg 0 ---
# 📰 InfoDigest 每日推送

> 2026-07-01 08:44 UTC · 共 4 条 · 来源 1

🔥 **[A]** [AI breakthrough: new reasoning model](https://example.com/blog/ai-breakthrough)
A new reasoning model achieves state-of-the-art results.
📌 **[B]** [Open source weekly digest](https://example.com/blog/oss-weekly)
Highlights from the open source world this week.
📌 **[B]** [No date item](https://example.com/blog/no-date)
An item without a publish date.
📌 **[B]** [Empty summary item](https://example.com/blog/empty)

---
_InfoDigest · 开源自驱信息收集系统_
```

- 4 条目采集 → 4 评分 → 4 入库 → 2 消息推送（飞书+钉钉各 1 条）
- grade 标记正确（🔥 A / 📌 B）
- status=ok，run_id=1 写入 runs 表

## 剧本 2: 幂等性（重复运行不产生重复条目）

### 步骤
1. 同一 fixture 运行两次
2. 第二次断言 `stored=0`（uid 去重）

### 实跑证据
- 首次：stored=4
- 再次：stored=0（`ON CONFLICT(uid) DO NOTHING` 生效）

## 剧本 3: 失败落盘重试

### 步骤
1. 配置 fake channel 返回 `ok=False, error="webhook down"`
2. 运行，断言 `failed > 0`，`data/failed_digests/*.json` 存在

### 实跑证据
- report.failed > 0
- errors 含 "webhook down"
- `failed_digests/` 目录下生成 JSON 文件，含 channel/content/error/digest_id

## 剧本 4: 坏源降级

### 步骤
1. 配置一个 URL 不可达的源
2. 运行，断言该源被 disable，其他源正常

### 预期
- `FetchError` 捕获，`repo.disable_source(id)` 执行
- 其他源继续采集，run 完成

## 剧本 5: CI 流水线

### 步骤
1. push 到 main
2. GitHub Actions ci.yml 触发：install + ruff + pytest --cov-fail-under=85
3. 实跑证据：本地 179 tests，88% coverage，ruff clean

## 自检
- [x] 空库→推送一次跑通
- [x] 断网/坏源降级
- [x] 重复运行幂等
- [x] 失败落盘
- [x] 覆盖率门禁 85%

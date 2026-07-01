# DATA_MODEL.md — SQLite 数据模型

> 架构师产出。表结构、索引、字段语义。

## 概览

InfoDigest 使用单个 SQLite 文件库（`data/infodigest.db`，WAL 模式）。四张表：`sources`、`entries`、`digests`、`runs`。模块间通过 `Entry`/`ScoredEntry` dataclass 传值，不传 ORM 对象。

## ER 图

```
sources 1───* entries *───1 digests
  │                │
  └─ etag/lm       └─ digest_id (批次标记)
                    runs (独立运行日志)
```

## 表结构

### sources
源注册表镜像 + 增量缓存头。

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | slug（如 hackernews） |
| url | TEXT NOT NULL UNIQUE | RSS URL |
| category | TEXT | 类别（tech/ai/security...） |
| lang | TEXT | 语言（en/zh） |
| authority | REAL DEFAULT 0.5 | 源权威 0–1 |
| tags | TEXT | JSON array 字符串 |
| etag | TEXT | 增量：If-None-Match |
| last_modified | TEXT | 增量：If-Modified-Since |
| enabled | INTEGER DEFAULT 1 | 0=禁用（坏源自动降级） |
| created_at | TEXT | ISO8601 |

### entries
条目主表。uid 是去重主键。

| 列 | 类型 | 说明 |
|---|---|---|
| uid | TEXT PK | sha1(normalized_title + source_domain) |
| source_id | TEXT | 外键→sources.id（逻辑，无约束） |
| title | TEXT | 原始标题 |
| summary | TEXT | 清洗后纯文本摘要（≤500 字符） |
| link | TEXT | 条目链接 |
| published | TEXT | ISO8601 UTC 发布时间 |
| raw_score | REAL | 评分 0–100 |
| grade | TEXT | A/B/C |
| engagement | INTEGER | 热度（points/comments，可空） |
| digest_id | TEXT | 所属推送批次（NULL=未推送） |
| created_at | TEXT | ISO8601 入库时间 |

**索引**：
- `idx_entries_published` ON entries(published) — 时间范围查询
- `idx_entries_grade` ON entries(grade) — pending_digest 按分级过滤
- `idx_entries_source` ON entries(source_id) — 按源统计

### digests
推送批次记录。

| 列 | 类型 | 说明 |
|---|---|---|
| id | TEXT PK | UUID hex |
| created_at | TEXT | ISO8601 |
| channel | TEXT | feishu/dingtalk |
| entry_count | INTEGER | 批次条目数 |
| status | TEXT | pending/sent/failed |
| error | TEXT | 失败原因 |

### runs
运行日志。

| 列 | 类型 | 说明 |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| started_at | TEXT | |
| ended_at | TEXT | |
| collected | INTEGER | 采集数 |
| deduped | INTEGER | 去重丢弃数 |
| rated | INTEGER | 评分数 |
| delivered | INTEGER | 推送成功数 |
| status | TEXT | ok/partial/error |

## 迁移

`storage/models.py:migrate()` 用 `CREATE TABLE IF NOT EXISTS` 幂等建表。无版本号——schema 变更靠 IF NOT EXISTS + ALTER（当前无需迁移框架）。

## 关键查询

```sql
-- 待推送：grade ≥ B 且未推送
SELECT * FROM entries WHERE grade IN ('A','B') AND digest_id IS NULL
ORDER BY raw_score DESC, published DESC;

-- 近 7 天标题（模糊去重）
SELECT title FROM entries WHERE created_at >= ? ORDER BY created_at DESC;

-- 源增量缓存
SELECT etag, last_modified FROM sources WHERE id = ?;
```

## 一致性

- `upsert_entries` 用 `ON CONFLICT(uid) DO NOTHING` —— 重复条目跳过，幂等。
- `mark_entries_digest` 标记后 `pending_digest` 排除 —— 防重复推送。
- WAL 模式 + `PRAGMA synchronous=NORMAL` —— 性能与持久性平衡。

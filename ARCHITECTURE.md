# ARCHITECTURE.md — 模块契约与数据模型

## 目录骨架
```
info-digest/
├── README.md
├── pyproject.toml              # 构建+工具配置
├── requirements.txt            # 锁定依赖
├── .gitignore                  # 含 .env, data/*.db, __pycache__, .venv
├── config/
│   ├── settings.yaml           # 全局: 调度/存储路径/推送通道开关
│   ├── feeds.yaml              # RSS 源注册表
│   ├── rater.yaml              # 评分权重/关键词/阈值
│   └── templates/              # Jinja2 推送模板
│       ├── feishu_card.j2
│       ├── dingtalk_md.j2
│       └── digest_section.j2
├── infodigest/
│   ├── __init__.py
│   ├── cli.py                  # argparse: collect / rate / deliver / run
│   ├── config.py               # dataclass + yaml 加载
│   ├── collector/
│   │   ├── __init__.py
│   │   ├── fetcher.py          # httpx 增量抓取 (ETag/Last-Modified)
│   │   ├── parser.py           # feedparser 归一化为 Entry
│   │   ├── normalizer.py       # 统一 Entry schema + HTML 清洗
│   │   └── dedup.py            # hash + 标题相似度
│   ├── rater/
│   │   ├── __init__.py
│   │   └── scorer.py           # 规则评分 + 分级
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── models.py           # SQLite 表: entries, runs, sources, digests
│   │   └── repo.py             # 仓储: upsert/query/增量
│   ├── formatter/
│   │   ├── __init__.py
│   │   └── builder.py          # Jinja2 渲染 (纯构建, 无 LLM)
│   ├── delivery/
│   │   ├── __init__.py
│   │   ├── base.py             # Channel 抽象
│   │   ├── feishu.py           # interactive card
│   │   ├── dingtalk.py         # markdown + 签名
│   │   └── limiter.py          # 令牌桶限流
│   └── scheduler/
│       └── runner.py           # 编排 collect→rate→store→deliver
├── tests/
│   ├── conftest.py             # fixtures: 临时 db, 本地 feed 样本
│   ├── fixtures/
│   │   ├── rss2_sample.xml
│   │   ├── atom_sample.xml
│   │   └── bad_feed.xml
│   ├── test_fetcher.py
│   ├── test_parser.py
│   ├── test_normalizer.py
│   ├── test_dedup.py
│   ├── test_scorer.py
│   ├── test_repo.py
│   ├── test_formatter.py
│   ├── test_feishu.py
│   ├── test_dingtalk.py
│   └── test_runner.py
├── data/                       # 运行时产物 (gitignore)
│   ├── infodigest.db
│   └── failed_digests/
├── docs/
│   ├── REQUIREMENTS.md
│   ├── DESIGN.md
│   ├── DATA_MODEL.md
│   ├── UAT.md
│   └── CONTRIBUTING.md
├── scripts/
│   └── opml_import.py          # OPML → feeds.yaml
└── .github/workflows/
    ├── ci.yml
    ├── digest.yml
    └── release.yml
```

## 模块依赖 (单向, 无环)
```
config ──▶ collector ──▶ rater ──▶ storage ◀── formatter ◀── delivery
   ▲___________________________________________________│
                      scheduler.runner 编排以上
```
- `cli.py` 只编排，不含业务逻辑。
- 模块间通过 dataclass 传值，不传 ORM 对象。

## 数据模型 (SQLite)
```sql
CREATE TABLE sources (
  id TEXT PRIMARY KEY,           -- slug
  url TEXT NOT NULL UNIQUE,
  category TEXT, lang TEXT,
  authority REAL DEFAULT 0.5,
  tags TEXT,                     -- JSON array
  etag TEXT, last_modified TEXT, -- 增量
  enabled INTEGER DEFAULT 1,
  created_at TEXT
);
CREATE TABLE entries (
  uid TEXT PRIMARY KEY,          -- sha1(norm_title + domain)
  source_id TEXT, title TEXT, summary TEXT, link TEXT,
  published TEXT,                -- ISO8601
  raw_score REAL, grade TEXT,    -- A/B/C
  engagement INTEGER,
  digest_id TEXT,                -- 所属推送批次
  created_at TEXT
);
CREATE TABLE digests (
  id TEXT PRIMARY KEY,           -- ULID
  created_at TEXT, channel TEXT,
  entry_count INTEGER, status TEXT, error TEXT
);
CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT, ended_at TEXT,
  collected INTEGER, deduped INTEGER, rated INTEGER, delivered INTEGER,
  status TEXT
);
```
索引：`entries(published)`、`entries(grade)`、`entries(source_id)`。

## 接口契约 (关键签名)
```python
# collector/parser.py
@dataclass(frozen=True)
class Entry:
    uid: str; source_id: str; title: str; summary: str
    link: str; published: datetime | None; raw: dict

def parse(content: bytes, source: Source) -> list[Entry]: ...

# rater/scorer.py
@dataclass(frozen=True)
class ScoredEntry(Entry):
    raw_score: float; grade: str

def score(entry: Entry, ctx: ScoreContext) -> ScoredEntry: ...

# storage/repo.py
class Repo:
    def upsert_entries(self, es: list[Entry]) -> int: ...      # 返回新增数
    def recent_titles(self, since_days: int) -> list[str]: ...
    def pending_digest(self, grade_min: str) -> list[Entry]: ...

# delivery/base.py
class Channel(Protocol):
    def send(self, payload: bytes) -> None: ...

# scheduler/runner.py
def run(config: Config) -> RunReport: ...   # collect→rate→store→deliver
```

## 配置契约
- 所有可调参数在 `config/*.yaml`，代码用 `config.py` 的 dataclass 加载，禁止散落硬编码。
- 评分权重、关键词、阈值、推送阈值(grade_min)、调度表达式均可配。

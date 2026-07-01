# SOURCES_SEED.md — RSS 数据源种子与采集机制 (无 LLM)

## 采集机制设计

### 抓取 (fetcher)
- `httpx.Client(timeout=15, follow_redirects=True)`，默认 UA `InfoDigest/1.0 (+https://github.com/<owner>/info-digest)`。
- **增量**：缓存每源 `etag` / `last_modified` 于 `sources` 表；请求带 `If-None-Match` / `If-Modified-Since`；304 跳过。
- **重试**：5xx/超时指数退避 3 次；4xx(除 429) 标记源 `enabled=0` 并记 `runs` 日志；429 退避 60s 重试 1 次。
- **反爬**：尊重 `robots.txt`（抓取前校验）；限制单源并发=1。

### 解析 (parser)
- `feedparser.parse(content)`，兼容 RSS 2.0 / Atom 1.0 / RDF (RSS 1.0)。
- 字段映射：`title / link / summary(description/content) / published(parsed)`。
- 容错：缺 `published` 用抓取时间；缺 `link` 跳过；`summary` 为空则取 `content[0].value`。

### 归一化 (normalizer)
- HTML 清洗：BeautifulSoup(`lxml`) 去脚本/样式/标签，纯文本，折叠空白，摘要截断 500 字符。
- 标题归一化：小写、去标点、折叠空白、去常见前后缀（" - 博客园" 等）。
- 时间：`feedparser` 已解析为 `struct_time`，转 `datetime`(UTC) 存 ISO8601。

### 去重 (dedup)
- 主键 `uid = sha1(norm_title + source_domain)`。
- 二次：对近 7 天 `recent_titles` 算 Jaccard（按词集合），>0.8 视为重复，保留更早的一条。

## 源注册表 schema (`feeds.yaml`)
```yaml
sources:
  - id: hackernews
    url: https://hnrss.org/frontpage
    category: tech
    authority: 0.9
    lang: en
    tags: [news, startup, ai]
    enabled: true
  - id: ruanyifeng
    url: https://www.ruanyifeng.com/blog/atom.xml
    category: tech
    authority: 0.8
    lang: zh
    tags: [weekly, web]
    enabled: true
```

## 种子源清单 (按类别, 全部真实 RSS, AI 须逐条写入 feeds.yaml 并在采集层验证可达)

### 科技 / 综合
- Hacker News — https://hnrss.org/frontpage (authority 0.9, en)
- 阮一峰博客 — https://www.ruanyifeng.com/blog/atom.xml (0.8, zh)
- 博客园 — https://feed.cnblogs.com/blog/sitecateogry/108698/rss (0.7, zh)
- InfoQ 中文 — https://www.infoq.cn/feed (0.75, zh)
- V2EX — https://www.v2ex.com/index.xml (0.6, zh)

### AI / 机器学习
- MIT Tech Review AI — https://www.technologyreview.com/feed/ (0.85, en)
- 机器之心 — https://www.jiqizhixin.com/rss (0.8, zh)
- Papers with Code (blog) — https://paperswithcode.com/latest (0.7, en)

### 安全
- Hacker News (security) — https://hnrss.org/newest?point=100&q=security (0.7, en)
- SecWiki — https://www.sec-wiki.com/news/rss (0.75, zh)
- FreeBuf — https://www.freebuf.com/feed (0.7, zh)

### 开源
- GitHub Trending (经 rss bridge) — https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml (0.75, en)
- Linux Weekly News — https://lwn.net/headlines/rss (0.8, en)

### 产品 / 设计
- Product Hunt — https://www.producthunt.com/feed (0.75, en)
- Smashing Magazine — https://www.smashingmagazine.com/feed/ (0.8, en)

### 区块链
- 链闻 — https://www.chainnews.com/feed/ (0.7, zh)  [若失效则在 STATUS 标注并降权]

## 扩源规范
- 新源须先 `enabled: false` 试跑一轮，解析成功且无 4xx 后置 `true`。
- 每源 `authority` 由人工初值，进化循环可据历史推送质量调整。
- 欢迎社区贡献源：`docs/CONTRIBUTING.md` 给出提交 `feeds.yaml` PR 的规范。

# CONTRIBUTING.md — 贡献指南

> 欢迎向 InfoDigest 贡献！本指南说明如何添加 RSS 源、提交改进。

## 添加 RSS 源

1. Fork 仓库并克隆。
2. 编辑 `config/feeds.yaml`，在 `sources:` 下新增一条：

```yaml
- id: my_source           # slug，唯一
  url: https://example.com/rss
  category: tech           # tech/ai/security/opensource/product/design/blockchain
  authority: 0.6           # 0–1，初值由你判断，维护者可调
  lang: en                 # en/zh
  tags: [news, web]
  enabled: false           # 新源默认 false，试跑成功后置 true
```

3. 提交 PR，说明源名、类别、为何有价值。
4. 维护者会试跑一轮（`enabled: true`），解析成功且无 4xx 后合并。

## 源要求
- **真实可访问**的 RSS/Atom/RDF URL。
- 内容稳定、更新频率合理（每周至少 1 篇）。
- 不含违法/spam 内容。
- `authority` 建议值：头部媒体 0.8–0.9，垂直博客 0.6–0.8，社区 0.5–0.6。

## 提交代码改进

1. Fork → 分支 → PR。
2. 遵循约定式提交：`feat:` / `fix:` / `test:` / `refactor:` / `docs:` / `chore:` / `ci:`。
3. 每个功能一提交，含对应测试。
4. CI 必须绿：`ruff check` + `pytest --cov-fail-under=85`。
5. 不引入大模型依赖（铁律）。
6. 不硬编码密钥——走环境变量/GitHub Secrets。

## 本地开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest                 # 跑测试
ruff check infodigest tests scripts  # lint
python -m infodigest.cli sources     # 查看源列表
python -m infodigest.cli run         # 跑一次（需配置 webhook env）
```

## OPML 批量导入

```bash
python scripts/opml_import.py path/to/feeds.opml
# 新源以 enabled=false 导入，review 后手动启用
```

## 评分调参

修改 `config/rater.yaml`：
- `keywords`：关键词 → 权重（标题命中 ×1.0，摘要 ×0.4）
- `grade_thresholds`：A=75, B=50（可调）
- `weights`：五维权重（总和 100）

调参后跑 `tests/test_regression.py` 确保无回归。

## 行为准则
- 友善、尊重、聚焦技术。
- 不接受任何形式的歧视或人身攻击。
